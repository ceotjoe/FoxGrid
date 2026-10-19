"""Push notifications (Firebase Cloud Messaging HTTP v1) with a logging fallback."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Participant, PushToken

log = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


@dataclass(frozen=True)
class PushTarget:
    token: str
    platform: str


class PushSender(Protocol):
    async def send(
        self, targets: list[PushTarget], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        """Send to all targets; returns tokens the provider reports as invalid."""
        ...


class LogPushSender:
    """Used when no push provider is configured."""

    async def send(
        self, targets: list[PushTarget], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        log.info("push (no provider configured) to %d devices: %s - %s", len(targets), title, body)
        return []


class FcmPushSender:
    def __init__(
        self,
        project_id: str,
        credentials_file: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._project_id = project_id
        self._credentials_file = credentials_file
        self._client = client or httpx.AsyncClient(timeout=10)
        self._credentials: Any = None

    async def _access_token(self) -> str:
        def refresh() -> str:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            if self._credentials is None:
                self._credentials = service_account.Credentials.from_service_account_file(
                    self._credentials_file, scopes=[FCM_SCOPE]
                )
            if not self._credentials.valid:
                self._credentials.refresh(Request())
            return str(self._credentials.token)

        return await asyncio.to_thread(refresh)

    @staticmethod
    def build_message(token: str, title: str, body: str, data: dict[str, str]) -> dict[str, Any]:
        return {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": data,
                "android": {
                    "priority": "HIGH",
                    "notification": {"channel_id": "transmission", "sound": "default"},
                },
                "apns": {
                    "headers": {"apns-priority": "10"},
                    "payload": {
                        "aps": {"sound": "default", "interruption-level": "time-sensitive"}
                    },
                },
            }
        }

    async def send(
        self, targets: list[PushTarget], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        url = f"https://fcm.googleapis.com/v1/projects/{self._project_id}/messages:send"
        headers = {"Authorization": f"Bearer {await self._access_token()}"}
        invalid: list[str] = []
        for target in targets:
            resp = await self._client.post(
                url, json=self.build_message(target.token, title, body, data), headers=headers
            )
            if resp.status_code == 404 or (resp.status_code == 400 and "UNREGISTERED" in resp.text):
                invalid.append(target.token)
            elif resp.status_code >= 400:
                log.warning("FCM rejected a message: %s %s", resp.status_code, resp.text[:200])
        return invalid


def make_sender(settings: Settings) -> PushSender:
    if settings.fcm_project_id and settings.fcm_credentials_file:
        return FcmPushSender(settings.fcm_project_id, settings.fcm_credentials_file)
    return LogPushSender()


async def notify_transmission_started(
    sender: PushSender,
    sessionmaker: async_sessionmaker[AsyncSession],
    mission_id: uuid.UUID,
    starter_id: uuid.UUID,
    mission_name: str,
) -> None:
    """Push "interferer is transmitting" to everyone in the mission except the starter."""
    try:
        async with sessionmaker() as session:
            rows = (
                await session.execute(
                    select(PushToken.token, PushToken.platform)
                    .join(Participant, Participant.id == PushToken.participant_id)
                    .where(
                        Participant.mission_id == mission_id,
                        Participant.id != starter_id,
                        # not for pending, rejected or removed people
                        Participant.is_active.is_(True),
                        Participant.status == "active",
                    )
                )
            ).all()
            if not rows:
                return
            invalid = await sender.send(
                [PushTarget(t, p) for t, p in rows],
                "STÖRER SENDET",
                f"{mission_name}: Aussendung gestartet",
                {"type": "transmission_started", "mission_id": str(mission_id)},
            )
            if invalid:
                await session.execute(delete(PushToken).where(PushToken.token.in_(invalid)))
                await session.commit()
    except Exception:
        log.exception("push notification failed")
