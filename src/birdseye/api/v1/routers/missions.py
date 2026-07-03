"""
API v1 routers for missions and frames with pagination support.
mypy + ruff clean.
"""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from birdseye.core.config import settings

from ....db.models import Frame, Mission
from ....db.session import get_db
from ....tasks.processing import analyze_orthophoto, generate_orthomosaic
from ...schemas import (
    FrameDetail,
    FrameListItem,
    Location,
    MissionDetail,
    MissionListItem,
    MissionStatusLogSchema,
    PaginatedFrames,
    PaginatedMissions,
)

router = APIRouter(prefix="/missions", tags=["missions"])


def _to_location(geom: Any) -> Location | None:
    """Convert a GeoAlchemy2 POINT geometry to our Location model."""
    if geom is None:
        return None
    try:
        shape = to_shape(geom)
        if hasattr(shape, "x") and hasattr(shape, "y"):
            return Location(lon=float(shape.x), lat=float(shape.y))
    except Exception:
        pass
    return None


def _to_geojson(geom: Any) -> dict[str, Any] | None:
    """Convert any GeoAlchemy2 geometry to GeoJSON dict."""
    if geom is None:
        return None
    try:
        return mapping(to_shape(geom))
    except Exception:
        return None


@router.get("", response_model=PaginatedMissions)
def list_missions(
    db: Annotated[Session, Depends(get_db)],
    skip: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 20,
) -> PaginatedMissions:
    """List missions (newest first) with offset pagination."""
    total = db.query(func.count(Mission.id)).scalar() or 0

    db_missions = (
        db.query(Mission)
        .options(selectinload(Mission.status_logs))
        .order_by(Mission.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # mypy-friendly frame counts
    counts: dict[int, int] = {}
    if db_missions:
        mission_ids = [int(m.id) for m in db_missions]  # ensure int
        rows = (
            db.query(Frame.mission_id, func.count(Frame.id))
            .filter(Frame.mission_id.in_(mission_ids))
            .group_by(Frame.mission_id)
            .all()
        )
        for row in rows:
            mid = int(row[0])
            cnt = int(row[1])
            counts[mid] = cnt

    items: list[MissionListItem] = []
    for m in db_missions:
        center = _to_location(m.center_point)
        item = MissionListItem(
            id=int(m.id),
            created_at=m.created_at,
            updated_at=m.updated_at,
            status=m.status,
            original_filename=m.original_filename,
            duration_seconds=m.duration_seconds,
            file_size_bytes=m.file_size_bytes,
            error_message=m.error_message,
            center=center,
            frame_count=counts.get(int(m.id), 0),
            meta=getattr(m, "meta", {}) or {},
            status_logs=[MissionStatusLogSchema.model_validate(log) for log in m.status_logs],
        )
        items.append(item)

    return PaginatedMissions(total=total, items=items)


@router.get("/{mission_id}", response_model=MissionDetail)
def get_mission(
    mission_id: int,
    db: Session = Depends(get_db),  # noqa: B008
) -> MissionDetail:
    """Full mission detail with geospatial data."""
    mission = (
        db.query(Mission)
        .options(selectinload(Mission.status_logs))
        .filter(Mission.id == mission_id)
        .first()
    )
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    center = _to_location(mission.center_point)
    bbox = _to_geojson(mission.bounding_box)
    frame_count = (
        db.query(func.count(Frame.id)).filter(Frame.mission_id == mission_id).scalar() or 0
    )

    return MissionDetail(
        id=int(mission.id),
        created_at=mission.created_at,
        updated_at=mission.updated_at,
        status=mission.status,
        original_filename=mission.original_filename,
        duration_seconds=mission.duration_seconds,
        file_size_bytes=mission.file_size_bytes,
        error_message=mission.error_message,
        meta=mission.meta or {},
        center=center,
        bounding_box=bbox,
        frame_count=frame_count,
        orthophoto_path=mission.orthophoto_path,
        dsm_path=mission.dsm_path,
        point_cloud_path=mission.point_cloud_path,
        mesh_path=mission.mesh_path,
        orthophoto_download_url=(
            f"{settings.asset_base_url}/{mission.orthophoto_path}"
            if mission.orthophoto_path
            else None
        ),
        point_cloud_download_url=(
            f"{settings.asset_base_url}/{mission.point_cloud_path}"
            if mission.point_cloud_path
            else None
        ),
        mesh_download_url=(
            f"{settings.asset_base_url}/{mission.mesh_path}" if mission.mesh_path else None
        ),
        vegetation=(mission.meta or {}).get("vegetation") or {},  # type: ignore[call-overload]
        status_logs=[MissionStatusLogSchema.model_validate(log) for log in mission.status_logs],
    )


@router.get("/{mission_id}/frames", response_model=PaginatedFrames, tags=["frames"])
def list_mission_frames(
    mission_id: int,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    db: Session = Depends(get_db),  # noqa: B008
) -> PaginatedFrames:
    """Paged list of frames for a mission, ordered by time."""
    if not db.query(Mission.id).filter(Mission.id == mission_id).first():
        raise HTTPException(status_code=404, detail="Mission not found")

    total = db.query(func.count(Frame.id)).filter(Frame.mission_id == mission_id).scalar() or 0

    db_frames = (
        db.query(Frame)
        .filter(Frame.mission_id == mission_id)
        .order_by(Frame.relative_time_seconds.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    items: list[FrameListItem] = []
    for f in db_frames:
        loc = _to_location(f.location)
        item = FrameListItem(
            id=int(f.id),
            mission_id=int(f.mission_id),
            relative_time_seconds=f.relative_time_seconds,
            frame_number=f.frame_number,
            location=loc,
            altitude_m=f.altitude_m,
            gimbal_pitch_deg=f.gimbal_pitch_deg,
            vegetation_index=f.vegetation_index,
            thumbnail_path=f.thumbnail_path,
            frame_path=f.frame_path,
            created_at=f.created_at,
        )
        items.append(item)

    return PaginatedFrames(total=total, items=items)


@router.get("/frames/{frame_id}", response_model=FrameDetail, tags=["frames"])
def get_frame(
    frame_id: int,
    db: Session = Depends(get_db),  # noqa: B008
) -> FrameDetail:
    """Single frame with full analysis metadata."""
    frame = db.query(Frame).filter(Frame.id == frame_id).first()
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")

    loc = _to_location(frame.location)

    return FrameDetail(
        id=int(frame.id),
        mission_id=int(frame.mission_id),
        relative_time_seconds=frame.relative_time_seconds,
        frame_number=frame.frame_number,
        location=loc,
        altitude_m=frame.altitude_m,
        gimbal_pitch_deg=frame.gimbal_pitch_deg,
        vegetation_index=frame.vegetation_index,
        thumbnail_path=frame.thumbnail_path,
        created_at=frame.created_at,
        frame_timestamp=frame.frame_timestamp,
        frame_path=frame.frame_path,
        analysis_metadata=frame.analysis_metadata or {},
    )


@router.post("/{mission_id}/orthomosaic", status_code=202)
def trigger_orthomosaic(
    mission_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    sample_interval_sec: float = Query(
        default=None,
        ge=0.5,
        le=10.0,
        description="Override frame sampling interval (seconds). Leave empty to use the value from original processing.",
    ),
):
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Store the sampling rate if provided (useful for re-processing)
    if sample_interval_sec is not None:
        if mission.meta is None:
            mission.meta = {}

        meta = dict(mission.meta)  # make a mutable copy
        meta["sample_interval_sec"] = sample_interval_sec
        mission.meta = meta  # type: ignore[assignment]
        db.commit()

    try:
        background_tasks.add_task(
            generate_orthomosaic,
            int(mission_id),
            sample_interval_sec,  # pass it through
        )
        return {
            "mission_id": mission_id,
            "status": "queued",
            "sample_interval_sec": sample_interval_sec
            or mission.meta.get("sample_interval_sec", 3.0),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/{mission_id}/debug/analyze-orthophoto")
def debug_analyze_orthophoto(mission_id: int, db: Annotated[Session, Depends(get_db)]):
    """Debug endpoint - trigger vegetation analysis on an existing orthophoto."""
    try:
        analyze_orthophoto(mission_id, db)

        # Re-fetch the mission to return latest stats
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        vegetation_stats = (mission.meta or {}).get("vegetation") or {} if mission else {}  # type: ignore[call-overload]

        return {
            "mission_id": mission_id,
            "status": "completed",
            "vegetation_stats": vegetation_stats,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
