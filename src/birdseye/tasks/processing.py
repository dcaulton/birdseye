"""
Background processing tasks for birdseye.
Includes structured logging for diagnostics (especially telemetry / location population).
"""

import contextlib
import shutil
from datetime import timedelta
from pathlib import Path

import cv2
import structlog
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPoint, Point
from sqlalchemy.orm import Session

from birdseye.analysis.vegetation import compute_vegetation_indices
from birdseye.core.config import settings
from birdseye.db.models import Frame, Mission
from birdseye.db.session import SessionLocal
from birdseye.extraction.srt_parser import parse_dji_srt

# Configure structlog (basic setup - can be enhanced later)
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

log = structlog.get_logger(__name__)

STORAGE_ROOT = Path(settings.storage_root)
SAMPLE_INTERVAL_SEC = 3.0


def process_uploaded_video(
    mission_id: int,
    tmp_video_path: str,
    original_filename: str,
    tmp_srt_path: str | None = None,
    db: Session | None = None,
) -> None:
    if db is None:
        db = SessionLocal()
    mission = None
    try:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission:
            log.error("mission_not_found", mission_id=mission_id)
            return

        mission.status = "processing"
        db.commit()

        log.info(
            "processing_started",
            mission_id=mission_id,
            original_filename=original_filename,
            has_srt=tmp_srt_path is not None,
        )

        mission_dir = STORAGE_ROOT / "missions" / str(mission_id)
        video_dir = mission_dir / "video"
        frames_dir = mission_dir / "frames"
        thumbs_dir = mission_dir / "thumbnails"
        for d in (video_dir, frames_dir, thumbs_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Move video
        final_video = video_dir / Path(original_filename).name
        shutil.move(tmp_video_path, final_video)

        # Handle SRT
        srt_path = None
        telemetry = []
        if tmp_srt_path:
            final_srt = mission_dir / "flight.SRT"
            shutil.move(tmp_srt_path, final_srt)
            srt_path = final_srt
            try:
                telemetry = parse_dji_srt(srt_path)
                log.info(
                    "srt_parsed",
                    mission_id=mission_id,
                    telemetry_points=len(telemetry),
                    srt_path=str(srt_path),
                )
            except Exception as e:
                log.warning("srt_parse_failed", mission_id=mission_id, error=str(e))
                mission.error_message = f"SRT parse warning: {e}"
                db.commit()
        else:
            log.warning("no_srt_provided", mission_id=mission_id)

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
            "telemetry_points_parsed": len(telemetry),
        }
        db.commit()

        # Sample frames + analyze
        points_for_bbox: list[tuple[float, float]] = []
        sample_sec = 0.0
        frames_with_location = 0

        while sample_sec < duration:
            frame_idx = int(sample_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, bgr = cap.read()
            if not ret:
                sample_sec += SAMPLE_INTERVAL_SEC
                continue

            # Save frame + thumbnail
            frame_name = f"{int(sample_sec):06d}.jpg"
            frame_path = frames_dir / frame_name
            cv2.imwrite(str(frame_path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])

            thumb = cv2.resize(bgr, (320, 240), interpolation=cv2.INTER_AREA)
            thumb_path = thumbs_dir / frame_name
            cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])

            # Vegetation
            indices = compute_vegetation_indices(bgr)
            veg = indices["exg_mean"]

            # === Telemetry matching ===
            location = altitude = gimbal = None
            if telemetry:
                try:
                    closest = min(
                        telemetry, key=lambda t: abs(t.get("start_seconds", 0) - sample_sec)
                    )
                    lat = closest.get("lat")
                    lon = closest.get("lon")

                    if lat is not None and lon is not None:
                        if -180 <= float(lat) <= 180 and -90 <= float(lon) <= 90:
                            lat, lon = lon, lat
                        pt = Point(float(lon), float(lat))
                        location = from_shape(pt, srid=4326)
                        altitude = closest.get("alt_msl") or closest.get("rel_alt_m")
                        gimbal = closest.get("gimbal_pitch_deg")
                        points_for_bbox.append((float(lon), float(lat)))
                        frames_with_location += 1
                    else:
                        # Log first few failures so we can debug
                        if sample_sec < 10:
                            log.warning(
                                f"[{mission_id}] No lat/lon found in closest telemetry at {sample_sec}s. "
                                f"closest keys: {list(closest.keys())}, sample: {closest}"
                            )
                except Exception as e:
                    log.warning(f"[{mission_id}] Telemetry matching error at {sample_sec}s: {e}")

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

        # Aggregate mission geometry (with validation)
        if len(points_for_bbox) >= 2:
            try:
                mp = MultiPoint(points_for_bbox)
                mission.bounding_box = from_shape(mp.envelope, srid=4326)
                mission.center_point = from_shape(mp.centroid, srid=4326)
            except Exception as e:
                log.warning(f"[{mission_id}] Failed to build bounding box: {e}")
        elif len(points_for_bbox) == 1:
            # Fallback if only one point
            try:
                pt = Point(points_for_bbox[0])
                mission.center_point = from_shape(pt, srid=4326)
            except Exception as e:
                log.warning(
                    "single point bbox_calculation_failed", mission_id=mission_id, error=str(e)
                )

        log.info(
            f"[{mission_id}] Telemetry summary | "
            f"points_for_bbox={len(points_for_bbox)} | "
            f"frames_with_location={len([f for f in db.new if isinstance(f, Frame) and f.location])}"
        )
        mission.status = "completed"
        db.commit()

        log.info(
            "processing_completed",
            mission_id=mission_id,
            total_frames=int(sample_sec / SAMPLE_INTERVAL_SEC),
            frames_with_location=frames_with_location,
            has_geospatial_data=frames_with_location > 0,
        )

    except Exception as e:
        log.exception("processing_failed", mission_id=mission_id, error=str(e))
        if mission:
            mission.status = "failed"
            mission.error_message = str(e)[:500]
            db.commit()
        raise
    finally:
        db.close()
        for p in (tmp_video_path, tmp_srt_path):
            if p:
                with contextlib.suppress(Exception):
                    Path(p).unlink(missing_ok=True)
