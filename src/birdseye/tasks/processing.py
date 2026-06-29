"""
Background processing tasks for birdseye.
Includes structured logging for diagnostics (especially telemetry / location population).
"""

import contextlib
import logging
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

import cv2
import structlog
from geoalchemy2.shape import from_shape, to_shape
from pyodm import Node
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
logging.getLogger("birdseye").setLevel(logging.INFO)
log = structlog.get_logger(__name__)

STORAGE_ROOT = Path(settings.storage_root)


def process_uploaded_video(
    mission_id: int,
    tmp_video_path: str,
    original_filename: str,
    tmp_srt_path: str | None = None,
    db: Session | None = None,
    sample_interval_sec: float = 3.0,
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
            "sample_interval_sec": sample_interval_sec,
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
                sample_sec += sample_interval_sec
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

            sample_sec += sample_interval_sec

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
        _log_status(db, mission_id, "frames_extracted", "Frame extraction completed")
        db.commit()

        log.info(
            "processing_completed",
            mission_id=mission_id,
            total_frames=int(sample_sec / sample_interval_sec),
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


def generate_orthomosaic(mission_id: int, db: Session | None = None):
    if db is None:
        db = SessionLocal()

    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise ValueError(f"Mission {mission_id} not found")

    frames_dir = Path(settings.storage_root) / "missions" / str(mission_id) / "frames"
    if not frames_dir.exists():
        raise FileNotFoundError(f"No frames found for mission {mission_id}")

    log.warning(f"[{mission_id}] Starting ODM task for orthomosaic generation")
    ortho_dir = Path(settings.storage_root) / "missions" / str(mission_id) / "orthomosaic"
    ortho_dir.mkdir(parents=True, exist_ok=True)

    # Prepare images + geo.txt for ODM
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_images = Path(tmpdir) / "images"
        tmp_images.mkdir()

        geo_lines = []
        for frame in (
            db.query(Frame)
            .filter(Frame.mission_id == mission_id)
            .order_by(Frame.relative_time_seconds)
        ):
            if frame.location is None:
                continue
            src = Path(settings.storage_root) / frame.frame_path
            dst = tmp_images / src.name
            shutil.copy2(src, dst)

            shape = to_shape(frame.location)
            lon = shape.x
            lat = shape.y
            alt = frame.altitude_m or 0
            geo_lines.append(f"{src.name} {lat} {lon} {alt}")

        if not geo_lines:
            raise ValueError("No frames with location data")

        (tmp_images / "geo.txt").write_text("\n".join(geo_lines))

        # Run ODM
        node = Node("localhost", 3000)  # assumes ODM is running on default port
        image_files = [str(p) for p in tmp_images.glob("*.jpg")]
        log.warning(f"[{mission_id}] Sending {len(image_files)} images to ODM")
        task = node.create_task(image_files, {"dsm": True, "orthophoto-resolution": 2.0})
        log.warning(f"[{mission_id}] ODM task started: {task.uuid}")
        task.wait_for_completion()
        log.warning(f"[{mission_id}] ODM task completed: {task.uuid}")

        # Copy outputs
        task.download_assets(str(ortho_dir))
        log.warning(f"[{mission_id}] Orthomosaic assets downloaded to {ortho_dir}")


def _log_status(db: Session, mission_id: int, status: str, message: str | None = None):
    from birdseye.db.models import Mission, MissionStatusLog

    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if mission:
        mission.status = status
        db.add(MissionStatusLog(mission_id=mission_id, status=status, message=message))
