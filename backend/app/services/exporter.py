"""GPX, KML, JSON and PDF protocol exports of a mission."""

from __future__ import annotations

import io
import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Bearing,
    BearingRevision,
    Estimate,
    Mission,
    Participant,
    PositionSample,
    Transmission,
)
from app.schemas.api import RevisionOut
from app.services.serialize import (
    bearing_out,
    estimate_out,
    event_json,
    mission_out,
    participant_out,
    position_out,
    transmission_out,
)

RAY_LENGTH_M = 25_000.0
EARTH_M_PER_DEG = 111_320.0


@dataclass
class MissionData:
    mission: Mission
    participants: dict[uuid.UUID, Participant]
    transmissions: list[Transmission]
    bearings: list[Bearing]
    revisions: list[BearingRevision]
    positions: list[PositionSample]
    estimate_all: Estimate | None
    estimate_current: Estimate | None
    callsigns: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def best_estimate(self) -> Estimate | None:
        return self.estimate_all or self.estimate_current


async def load_mission_data(session: AsyncSession, mission: Mission) -> MissionData:
    mid = mission.id
    participants = {
        p.id: p
        for p in (await session.scalars(select(Participant).where(Participant.mission_id == mid)))
    }
    transmissions = list(
        await session.scalars(
            select(Transmission).where(Transmission.mission_id == mid).order_by(Transmission.seq)
        )
    )
    bearings = list(
        await session.scalars(
            select(Bearing).where(Bearing.mission_id == mid).order_by(Bearing.measured_at)
        )
    )
    revisions = list(
        await session.scalars(
            select(BearingRevision)
            .join(Bearing, Bearing.id == BearingRevision.bearing_id)
            .where(Bearing.mission_id == mid)
            .order_by(BearingRevision.id)
        )
    )
    positions = list(
        await session.scalars(
            select(PositionSample)
            .where(PositionSample.mission_id == mid)
            .order_by(PositionSample.recorded_at)
        )
    )
    estimates: dict[str, Estimate | None] = {}
    for scope in ("all", "current"):
        estimates[scope] = await session.scalar(
            select(Estimate)
            .where(Estimate.mission_id == mid, Estimate.scope == scope)
            .order_by(Estimate.computed_at.desc())
            .limit(1)
        )
    return MissionData(
        mission=mission,
        participants=participants,
        transmissions=transmissions,
        bearings=bearings,
        revisions=revisions,
        positions=positions,
        estimate_all=estimates["all"],
        estimate_current=estimates["current"],
        callsigns={pid: p.callsign for pid, p in participants.items()},
    )


def _destination(lat: float, lon: float, azimuth_deg: float, meters: float) -> tuple[float, float]:
    """Point at ``meters`` along a true azimuth (spherical earth, fine for 25 km rays)."""
    r = 6_371_000.0
    d = meters / r
    brg = math.radians(azimuth_deg)
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(brg))
    lo2 = lo1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(la1), math.cos(d) - math.sin(la1) * math.sin(la2)
    )
    return math.degrees(la2), (math.degrees(lo2) + 540.0) % 360.0 - 180.0


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tracks(data: MissionData) -> dict[uuid.UUID, list[PositionSample]]:
    tracks: dict[uuid.UUID, list[PositionSample]] = {}
    for p in data.positions:
        tracks.setdefault(p.participant_id, []).append(p)
    return tracks


def _bearing_label(data: MissionData, b: Bearing) -> str:
    who = data.callsigns.get(b.participant_id, "?")
    flag = " [Ausreißer]" if b.is_outlier else ""
    flag += " [inaktiv]" if not b.is_active else ""
    return f"{who} {float(b.azimuth_true_deg):.0f}° ±{float(b.sigma_deg):.0f}°{flag}"


# --- GPX ---------------------------------------------------------------------------------


def build_gpx(data: MissionData) -> bytes:
    gpx = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": "FoxGrid",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    meta = ET.SubElement(gpx, "metadata")
    ET.SubElement(meta, "name").text = data.mission.name
    ET.SubElement(meta, "time").text = _iso(datetime.now(UTC))

    est = data.best_estimate
    if est:
        wpt = ET.SubElement(gpx, "wpt", {"lat": f"{est.lat:.7f}", "lon": f"{est.lon:.7f}"})
        ET.SubElement(wpt, "name").text = "Störer (Schätzung)"
        major = est.ellipse_1s["semi_major_m"]
        minor = est.ellipse_1s["semi_minor_m"]
        ET.SubElement(
            wpt, "desc"
        ).text = f"{est.n_bearings} Peilungen, 1σ-Ellipse {major:.0f} x {minor:.0f} m"
    for b in data.bearings:
        wpt = ET.SubElement(gpx, "wpt", {"lat": f"{b.lat:.7f}", "lon": f"{b.lon:.7f}"})
        ET.SubElement(wpt, "time").text = _iso(b.measured_at)
        ET.SubElement(wpt, "name").text = _bearing_label(data, b)
        ET.SubElement(wpt, "desc").text = b.note or ""
    for b in data.bearings:
        rte = ET.SubElement(gpx, "rte")
        ET.SubElement(rte, "name").text = f"Peilstrahl {_bearing_label(data, b)}"
        end_lat, end_lon = _destination(b.lat, b.lon, float(b.azimuth_true_deg), RAY_LENGTH_M)
        for lat, lon in ((b.lat, b.lon), (end_lat, end_lon)):
            ET.SubElement(rte, "rtept", {"lat": f"{lat:.7f}", "lon": f"{lon:.7f}"})
    for pid, samples in _tracks(data).items():
        trk = ET.SubElement(gpx, "trk")
        ET.SubElement(trk, "name").text = data.callsigns.get(pid, "?")
        seg = ET.SubElement(trk, "trkseg")
        for s in samples:
            pt = ET.SubElement(seg, "trkpt", {"lat": f"{s.lat:.7f}", "lon": f"{s.lon:.7f}"})
            ET.SubElement(pt, "time").text = _iso(s.recorded_at)
    ET.indent(gpx)
    return ET.tostring(gpx, encoding="utf-8", xml_declaration=True)


# --- KML ---------------------------------------------------------------------------------


def _coords(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{lon:.7f},{lat:.7f},0" for lon, lat in points)


def _kml_polygon(parent: ET.Element, name: str, ring: list[Any], style: str) -> None:
    pm = ET.SubElement(parent, "Placemark")
    ET.SubElement(pm, "name").text = name
    ET.SubElement(pm, "styleUrl").text = f"#{style}"
    poly = ET.SubElement(pm, "Polygon")
    outer = ET.SubElement(ET.SubElement(poly, "outerBoundaryIs"), "LinearRing")
    ET.SubElement(outer, "coordinates").text = _coords([(p[0], p[1]) for p in ring])


def build_kml(data: MissionData) -> bytes:
    kml = ET.Element("kml", {"xmlns": "http://www.opengis.net/kml/2.2"})
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = data.mission.name
    # KML colours are aabbggrr
    for sid, colour, width in (
        ("ray", "ff3030e0", 3),
        ("outlier", "ff30a0ff", 2),
        ("track", "ffe08030", 3),
    ):
        st = ET.SubElement(doc, "Style", {"id": sid})
        ls = ET.SubElement(st, "LineStyle")
        ET.SubElement(ls, "color").text = colour
        ET.SubElement(ls, "width").text = str(width)
    for sid, colour in (
        ("e1", "552020ff"),
        ("e2", "331010ff"),
        ("c50", "552020ff"),
        ("c80", "33ff8020"),
        ("c95", "22ff8020"),
    ):
        st = ET.SubElement(doc, "Style", {"id": sid})
        ET.SubElement(ET.SubElement(st, "PolyStyle"), "color").text = colour

    est = data.best_estimate
    if est:
        folder = ET.SubElement(doc, "Folder")
        ET.SubElement(folder, "name").text = "Schätzung"
        pm = ET.SubElement(folder, "Placemark")
        ET.SubElement(pm, "name").text = "Störer (Schätzung)"
        ET.SubElement(pm, "description").text = f"{est.n_bearings} Peilungen"
        pt = ET.SubElement(pm, "Point")
        ET.SubElement(pt, "coordinates").text = f"{est.lon:.7f},{est.lat:.7f},0"
        for label, key, style in (("2σ", "ellipse_2s", "e2"), ("1σ", "ellipse_1s", "e1")):
            ring = getattr(est, key)["polygon"]["coordinates"][0]
            _kml_polygon(folder, f"Ellipse {label}", ring, style)
        for mass, polys in sorted((est.contours or {}).items(), key=lambda kv: -int(kv[0])):
            for i, poly in enumerate(polys):
                _kml_polygon(folder, f"{mass} % ({i + 1})", poly["coordinates"][0], f"c{mass}")

    folder = ET.SubElement(doc, "Folder")
    ET.SubElement(folder, "name").text = "Peilungen"
    for b in data.bearings:
        pm = ET.SubElement(folder, "Placemark")
        ET.SubElement(pm, "name").text = _bearing_label(data, b)
        ET.SubElement(pm, "styleUrl").text = "#outlier" if b.is_outlier else "#ray"
        ts = ET.SubElement(pm, "TimeStamp")
        ET.SubElement(ts, "when").text = _iso(b.measured_at)
        end_lat, end_lon = _destination(b.lat, b.lon, float(b.azimuth_true_deg), RAY_LENGTH_M)
        line = ET.SubElement(pm, "LineString")
        ET.SubElement(line, "coordinates").text = _coords([(b.lon, b.lat), (end_lon, end_lat)])

    folder = ET.SubElement(doc, "Folder")
    ET.SubElement(folder, "name").text = "Spuren"
    for pid, samples in _tracks(data).items():
        pm = ET.SubElement(folder, "Placemark")
        ET.SubElement(pm, "name").text = data.callsigns.get(pid, "?")
        ET.SubElement(pm, "styleUrl").text = "#track"
        line = ET.SubElement(pm, "LineString")
        ET.SubElement(line, "coordinates").text = _coords([(s.lon, s.lat) for s in samples])
    ET.indent(kml)
    return ET.tostring(kml, encoding="utf-8", xml_declaration=True)


# --- JSON --------------------------------------------------------------------------------


def build_json(data: MissionData) -> bytes:
    estimates = [e for e in (data.estimate_all, data.estimate_current) if e is not None]
    doc = {
        "format": "foxgrid-export/1",
        "exported_at": _iso(datetime.now(UTC)),
        "mission": event_json(mission_out(data.mission)),
        "participants": [event_json(participant_out(p)) for p in data.participants.values()],
        "transmissions": [event_json(transmission_out(t)) for t in data.transmissions],
        "bearings": [event_json(bearing_out(b)) for b in data.bearings],
        "bearing_revisions": [event_json(RevisionOut.model_validate(r)) for r in data.revisions],
        "estimates": [event_json(estimate_out(e)) for e in estimates],
        "positions": [event_json(position_out(p)) for p in data.positions],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False).encode()


# --- PDF ---------------------------------------------------------------------------------


def _clip_segment(
    p0: tuple[float, float], p1: tuple[float, float], box: tuple[float, float, float, float]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Liang-Barsky clipping of a segment to ``(xmin, ymin, xmax, ymax)``."""
    xmin, ymin, xmax, ymax = box
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, p0[0] - xmin), (dx, xmax - p0[0]), (-dy, p0[1] - ymin), (dy, ymax - p0[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    return (p0[0] + t0 * dx, p0[1] + t0 * dy), (p0[0] + t1 * dx, p0[1] + t1 * dy)


def _nice_length(meters: float) -> float:
    exp = math.floor(math.log10(meters))
    for m in (1, 2, 5, 10):
        if m * 10**exp >= meters:
            return float(m * 10**exp)
    return float(10 ** (exp + 1))  # pragma: no cover


def _map_drawing(data: MissionData, width: float, height: float) -> Any:
    from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String
    from reportlab.lib import colors

    est = data.best_estimate
    points: list[tuple[float, float]] = [(b.lon, b.lat) for b in data.bearings]
    if est:
        points.append((est.lon, est.lat))
        points += [(p[0], p[1]) for p in est.ellipse_2s["polygon"]["coordinates"][0]]
        for poly in (est.contours or {}).get("95", []):
            points += [(p[0], p[1]) for p in poly["coordinates"][0]]
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f2f2ee"), strokeColor=colors.grey))
    if not points:
        d.add(String(width / 2, height / 2, "Keine Daten", textAnchor="middle"))
        return d

    lat0 = sum(p[1] for p in points) / len(points)
    lon0 = sum(p[0] for p in points) / len(points)
    kx = EARTH_M_PER_DEG * math.cos(math.radians(lat0))

    def to_m(lon: float, lat: float) -> tuple[float, float]:
        return (lon - lon0) * kx, (lat - lat0) * EARTH_M_PER_DEG

    pm = [to_m(*p) for p in points]
    xmin, xmax = min(p[0] for p in pm), max(p[0] for p in pm)
    ymin, ymax = min(p[1] for p in pm), max(p[1] for p in pm)
    span = max(xmax - xmin, ymax - ymin, 500.0) * 1.2
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    margin = 18.0
    scale = (min(width, height) - 2 * margin) / span
    ox, oy = width / 2 - cx * scale, height / 2 - cy * scale

    def to_px(lon: float, lat: float) -> tuple[float, float]:
        x, y = to_m(lon, lat)
        return x * scale + ox, y * scale + oy

    box = (2.0, 2.0, width - 2.0, height - 2.0)

    def draw_poly(ring: list[Any], fill: Any, stroke: Any) -> None:
        flat: list[float] = []
        for p in ring:
            flat += list(to_px(p[0], p[1]))
        d.add(Polygon(flat, fillColor=fill, strokeColor=stroke, strokeWidth=0.8))

    if est:
        for mass, fill in (
            ("95", colors.Color(0.9, 0.3, 0.3, 0.12)),
            ("80", colors.Color(0.9, 0.3, 0.3, 0.2)),
            ("50", colors.Color(0.9, 0.2, 0.2, 0.3)),
        ):
            for pg in (est.contours or {}).get(mass, []):
                draw_poly(pg["coordinates"][0], fill, colors.Color(0.8, 0.1, 0.1, 0.7))
        draw_poly(est.ellipse_1s["polygon"]["coordinates"][0], None, colors.HexColor("#b00020"))

    palette = [
        colors.HexColor(c)
        for c in (
            "#3f51b5",
            "#009688",
            "#ff5722",
            "#9c27b0",
            "#795548",
            "#607d8b",
            "#e91e63",
            "#4caf50",
        )
    ]
    colour_of = {pid: palette[i % len(palette)] for i, pid in enumerate(data.callsigns)}
    for b in data.bearings:
        col = colour_of.get(b.participant_id, colors.black)
        start = to_px(b.lon, b.lat)
        end_lat, end_lon = _destination(b.lat, b.lon, float(b.azimuth_true_deg), span * 2)
        seg = _clip_segment(start, to_px(end_lon, end_lat), box)
        if seg:
            line = Line(*seg[0], *seg[1], strokeColor=col, strokeWidth=1.1)
            if b.is_outlier or not b.is_active:
                line.strokeDashArray = [3, 3]
            d.add(line)
        d.add(Circle(*start, 2.4, fillColor=col, strokeColor=colors.white, strokeWidth=0.4))
        d.add(
            String(
                start[0] + 4,
                start[1] + 3,
                data.callsigns.get(b.participant_id, "?"),
                fontSize=6.5,
                fillColor=col,
            )
        )
    if est:
        ex, ey = to_px(est.lon, est.lat)
        d.add(Line(ex - 6, ey, ex + 6, ey, strokeColor=colors.red, strokeWidth=1.6))
        d.add(Line(ex, ey - 6, ex, ey + 6, strokeColor=colors.red, strokeWidth=1.6))
        d.add(Circle(ex, ey, 4, fillColor=None, strokeColor=colors.red, strokeWidth=1.2))

    # scale bar and north arrow
    bar_m = _nice_length(span * 0.2)
    bar_px = bar_m * scale
    d.add(Line(10, 10, 10 + bar_px, 10, strokeColor=colors.black, strokeWidth=1.5))
    label = f"{bar_m / 1000:g} km" if bar_m >= 1000 else f"{bar_m:g} m"
    d.add(String(10, 14, label, fontSize=7))
    d.add(
        Line(
            width - 14,
            height - 34,
            width - 14,
            height - 12,
            strokeColor=colors.black,
            strokeWidth=1.5,
        )
    )
    d.add(
        Polygon(
            [width - 14, height - 8, width - 18, height - 18, width - 10, height - 18],
            fillColor=colors.black,
        )
    )
    d.add(String(width - 14, height - 46, "N", fontSize=8, textAnchor="middle"))
    return d


def build_pdf(data: MissionData) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"FoxGrid-Protokoll {data.mission.name}",
        author="FoxGrid",
    )
    m = data.mission
    story: list[Any] = [
        Paragraph(f"Peilprotokoll: {_esc(m.name)}", styles["Title"]),
        Paragraph(
            f"Frequenz {float(m.frequency_mhz):.4f} MHz · Status {m.status} · "
            f"Beginn {_iso(m.created_at)}" + (f" · Ende {_iso(m.ended_at)}" if m.ended_at else ""),
            styles["Normal"],
        ),
        Paragraph(f"Erstellt {_iso(datetime.now(UTC))} (UTC)", styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph("Ergebnis", styles["Heading2"]),
    ]
    est = data.best_estimate
    if est:
        story.append(
            Paragraph(
                f"Wahrscheinlichster Standort: <b>{est.lat:.5f}° N, {est.lon:.5f}° E</b> "
                f"(aus {est.n_bearings} Peilungen). 1σ-Ellipse "
                f"{est.ellipse_1s['semi_major_m']:.0f} × {est.ellipse_1s['semi_minor_m']:.0f} m, "
                f"Hauptachse {est.ellipse_1s['orientation_deg']:.0f}°; 2σ-Ellipse "
                f"{est.ellipse_2s['semi_major_m']:.0f} × {est.ellipse_2s['semi_minor_m']:.0f} m.",
                styles["Normal"],
            )
        )
    else:
        story.append(
            Paragraph("Noch keine Schätzung (mindestens zwei Peilungen nötig).", styles["Normal"])
        )
    story += [
        Spacer(1, 4 * mm),
        Paragraph("Karte (schematisch, Norden oben)", styles["Heading2"]),
        _map_drawing(data, 180 * mm, 120 * mm),
        Paragraph(
            "Rot: Wahrscheinlichkeitsmasse 50/80/95 % und 1σ-Ellipse · "
            "gestrichelt: Ausreißer/inaktiv",
            styles["Italic"],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Peilungen", styles["Heading2"]),
    ]
    tx_seq = {t.id: t.seq for t in data.transmissions}
    rows = [["Zeit (UTC)", "Peiler", "Azimut", "σ", "RSSI", "Aussendung", "Status", "Notiz"]]
    for b in data.bearings:
        status = "Ausreißer" if b.is_outlier else ("inaktiv" if not b.is_active else "ok")
        rows.append(
            [
                b.measured_at.astimezone(UTC).strftime("%d.%m. %H:%M:%S"),
                data.callsigns.get(b.participant_id, "?"),
                f"{float(b.azimuth_true_deg):.1f}°",
                f"±{float(b.sigma_deg):.0f}°",
                "" if b.rssi_dbm is None else f"{b.rssi_dbm:.0f} dBm",
                str(tx_seq.get(b.transmission_id, "–")) if b.transmission_id else "–",
                status,
                Paragraph(_esc(b.note or ""), styles["BodyText"]),
            ]
        )
    story.append(
        _table(
            rows,
            [24 * mm, 20 * mm, 17 * mm, 12 * mm, 18 * mm, 20 * mm, 20 * mm, 49 * mm],
        )
    )

    story += [Spacer(1, 6 * mm), Paragraph("Aussendungen", styles["Heading2"])]
    trows = [["Nr.", "Beginn (UTC)", "Ende (UTC)"]]
    for t in data.transmissions:
        trows.append(
            [
                str(t.seq),
                _iso(t.started_at),
                _iso(t.ended_at) if t.ended_at else "läuft",
            ]
        )
    story.append(_table(trows, [15 * mm, 60 * mm, 60 * mm]))

    story += [Spacer(1, 6 * mm), Paragraph("Teilnehmer", styles["Heading2"])]
    prow = [["Rufzeichen", "Rolle"]] + [[p.callsign, p.role] for p in data.participants.values()]
    story.append(_table(prow, [40 * mm, 30 * mm]))
    doc.build(story)
    return buf.getvalue()


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(rows: list[list[Any]], widths: list[float]) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t
