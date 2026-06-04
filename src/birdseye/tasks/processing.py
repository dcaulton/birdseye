"""
Background processing tasks for birdseye.
"""

import contextlib
import shutil
from datetime import timedelta
from pathlib import Path

import cv2
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPoint, Point

from birdseye.analysis.vegetation import compute_vegetation_indices
from birdseye.core.config import settings
from birdseye.db.models import Frame, Mission
from birdseye.db.session import SessionLocal
from birdseye.extraction.srt_parser import parse_dji_srt

STORAGE_ROOT = Path(settings.storage_root)
SAMPLE_INTERVAL_SEC = 3.0  # tune per mission density needs


def process_uploaded_video(
    mission_id: int,
    tmp_video_path: str,
    original_filename: str,
    tmp_srt_path: str | None = None,
) -> None:
    db = SessionLocal()
    mission = None
    try:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission:
            return

        mission.status = "processing"
        db.commit()

        mission_dir = STORAGE_ROOT / "missions" / str(mission_id)
        video_dir = mission_dir / "video"
        frames_dir = mission_dir / "frames"
        thumbs_dir = mission_dir / "thumbnails"
        for d in (video_dir, frames_dir, thumbs_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Move video to final storage
        final_video = video_dir / Path(original_filename).name
        shutil.move(tmp_video_path, final_video)

        srt_path = None
        telemetry = []
        if tmp_srt_path:
            final_srt = mission_dir / "flight.SRT"
            shutil.move(tmp_srt_path, final_srt)
            srt_path = final_srt
            try:
                telemetry = parse_dji_srt(srt_path)
            except Exception as e:
                mission.error_message = f"SRT parse warning: {e}"
                db.commit()

        # Video metadata
        cap = cv2.VideoCapture(str(final_video))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if fps > 0 else 0.0
        mission.duration_seconds = round(duration, 1)
        mission.file_size_bytes = final_video.stat().st_size
        mission.meta = {
            "video_path": str(final_video.relative_to(STORAGE_ROOT)),
            "srt_path": str(srt_path.relative_to(STORAGE_ROOT)) if srt_path else None,
            "fps": fps,
            "sample_interval_sec": SAMPLE_INTERVAL_SEC,
        }
        db.commit()

        # Sample frames + analyze
        points_for_bbox: list[tuple[float, float]] = []
        sample_sec = 0.0
        while sample_sec < duration:
            frame_idx = int(sample_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, bgr = cap.read()
            if not ret:
                sample_sec += SAMPLE_INTERVAL_SEC
                continue

            # Save full frame + thumbnail
            frame_name = f"{int(sample_sec):06d}.jpg"
            frame_path = frames_dir / frame_name
            cv2.imwrite(str(frame_path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])

            thumb = cv2.resize(bgr, (320, 240), interpolation=cv2.INTER_AREA)
            thumb_path = thumbs_dir / frame_name
            cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])

            # Vegetation
            indices = compute_vegetation_indices(bgr)
            veg = indices["exg_mean"]

            # Closest telemetry match
            location = altitude = gimbal = None
            if telemetry:
                closest = min(telemetry, key=lambda t: abs(t["start_seconds"] - sample_sec))
                if closest["lat"] is not None and closest["lon"] is not None:
                    pt = Point(closest["lon"], closest["lat"])
                    location = from_shape(pt, srid=4326)
                    altitude = closest.get("alt_msl") or closest.get("rel_alt_m")
                    gimbal = closest.get("gimbal_pitch_deg")
                    points_for_bbox.append((closest["lon"], closest["lat"]))

            frame_rec = Frame(
                mission_id=mission_id,
                frame_timestamp=mission.created_at + timedelta(seconds=sample_sec),
                frame_number=frame_idx,
                relative_time_seconds=round(sample_sec, 2),
                location=location,
                altitude_m=altitude,
                gimbal_pitch_deg=gimbal,
                frame_path=str(frame_path.relative_to(STORAGE_ROOT)),
                thumbnail_path=str(thumb_path.relative_to(STORAGE_ROOT)),
                vegetation_index=veg,
                analysis_metadata=indices,
            )
            db.add(frame_rec)

            sample_sec += SAMPLE_INTERVAL_SEC

        cap.release()

        # Aggregate mission geometry
        if points_for_bbox:
            mp = MultiPoint(points_for_bbox)
            mission.bounding_box = from_shape(mp.envelope, srid=4326)
            mission.center_point = from_shape(mp.centroid, srid=4326)

        mission.status = "completed"
        db.commit()

    except Exception as e:
        if mission:
            mission.status = "failed"
            mission.error_message = str(e)[:500]
            db.commit()
        raise
    finally:
        db.close()
        # cleanup any leftover temps (belt & suspenders)
        for p in (tmp_video_path, tmp_srt_path):
            if p:
                with contextlib.suppress(Exception):
                    Path(p).unlink(missing_ok=True)
