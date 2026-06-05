"""
SRT parser for DJI drone telemetry (Neo 2 and similar).
Lightweight, no external deps beyond stdlib + regex.
"""

import contextlib
import re
from pathlib import Path
from typing import Any


def _parse_timecode_to_seconds(tc: str) -> float:
    tc = tc.strip().replace(",", ".")
    parts = tc.split(":")
    if len(parts) == 3:
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        except ValueError:
            pass
    return 0.0


def parse_dji_srt(srt_path: Path | str) -> list[dict[str, Any]]:
    """Returns sorted list of telemetry dicts with lat/lon/alt/rel_alt/gimbal_pitch etc."""
    srt_path = Path(srt_path)
    if not srt_path.is_file():
        raise FileNotFoundError(srt_path)

    content = srt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n+", content.strip())
    telemetry: list[dict[str, Any]] = []

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue

        time_line = next((ln for ln in lines if "-->" in ln), None)
        if not time_line:
            continue

        parts = [p.strip() for p in time_line.split("-->")]
        if len(parts) != 2:
            continue
        start_sec = _parse_timecode_to_seconds(parts[0])
        end_sec = _parse_timecode_to_seconds(parts[1])

        meta = " ".join(ln for ln in lines if "-->" not in ln and not ln.isdigit())

        # GPS (lat, lon, alt_msl)
        gps = re.search(r"GPS\s*\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)", meta, re.I)
        lat = lon = alt_msl = None
        if gps:
            lat, lon, alt_msl = map(float, gps.groups())

        # D xxxm (relative altitude from takeoff)
        rel_alt = None
        if m := re.search(r"\bD\s+([-\d.]+)\s*m\b", meta, re.I):
            rel_alt = float(m.group(1))

        # Fallback parser for newer DJI SRT format (e.g. Neo) that uses [latitude: xx] [longitude: yy]
        if lat is None or lon is None:
            lat_match = re.search(r"\[latitude:\s*([-\d.]+)\]", meta, re.IGNORECASE)
            lon_match = re.search(r"\[longitude:\s*([-\d.]+)\]", meta, re.IGNORECASE)
            if lat_match and lon_match:
                lat = float(lat_match.group(1))
                lon = float(lon_match.group(1))

            # Also try to get rel_alt if not already found
            if rel_alt is None:
                rel_match = re.search(r"\[rel_alt:\s*([-\d.]+)\]", meta, re.IGNORECASE)
                if rel_match:
                    rel_alt = float(rel_match.group(1))

        # H xxxm (height)
        height = None
        if m := re.search(r"\bH\s+([-\d.]+)\s*m\b", meta, re.I):
            height = float(m.group(1))

        # Gimbal pitch (various spellings)
        gimbal_pitch = None
        if m := re.search(
            r"(?:Gimbal\s*Pitch|Pitch|G\.?P\.?)\s*[:=]?\s*([-+]?\d+\.?\d*)", meta, re.I
        ):
            with contextlib.suppress(ValueError):
                gimbal_pitch = float(m.group(1))

        telemetry.append(
            {
                "start_seconds": round(start_sec, 3),
                "end_seconds": round(end_sec, 3),
                "lat": lat,
                "lon": lon,
                "alt_msl": alt_msl,
                "rel_alt_m": rel_alt,
                "height_m": height,
                "gimbal_pitch_deg": gimbal_pitch,
                "raw_meta": meta[:300],
            }
        )

    telemetry.sort(key=lambda x: x["start_seconds"])
    return telemetry
