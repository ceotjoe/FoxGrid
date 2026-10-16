"""Exports (GPX, KML, JSON, PDF) and the declination lookup."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_participant, member
from app.db import get_session
from app.models import Mission, Participant
from app.schemas.api import DeclinationOut
from app.services import declination, exporter

router = APIRouter()

_FORMATS = {
    "gpx": ("application/gpx+xml", exporter.build_gpx),
    "kml": ("application/vnd.google-earth.kml+xml", exporter.build_kml),
    "json": ("application/json", exporter.build_json),
    "pdf": ("application/pdf", exporter.build_pdf),
}


@router.get("/missions/{mission_id}/export.{fmt}")
async def export_mission(
    mission_id: uuid.UUID,
    fmt: Literal["gpx", "kml", "json", "pdf"],
    _: Participant = Depends(member),
    session: AsyncSession = Depends(get_session),
) -> Response:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    media_type, build = _FORMATS[fmt]
    data = await exporter.load_mission_data(session, mission)
    safe = "".join(c if c.isalnum() else "_" for c in mission.name)[:40] or "mission"
    return Response(
        build(data),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="foxgrid_{safe}.{fmt}"'},
    )


@router.get("/declination", response_model=DeclinationOut)
async def get_declination(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    on: date | None = Query(default=None, alias="date"),
    _: Participant = Depends(current_participant),
) -> DeclinationOut:
    on = on or date.today()
    return DeclinationOut(
        lat=lat,
        lon=lon,
        date=on.isoformat(),
        declination_deg=round(declination.declination_deg(lat, lon, on), 2),
        model=declination.MODEL,
    )
