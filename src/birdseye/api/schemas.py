"""
Pydantic response schemas for birdseye API.
All models are designed to be mypy + ruff clean and serializable.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Location(BaseModel):
    """Simple lon/lat representation for API responses."""

    lon: float
    lat: float


class MissionStatusLogSchema(BaseModel):
    id: int
    status: str
    message: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MissionListItem(BaseModel):
    id: int
    created_at: datetime
    status: str
    original_filename: str
    duration_seconds: float | None = None
    file_size_bytes: int | None = None
    error_message: str | None = None
    center: Location | None = None
    frame_count: int = 0
    meta: dict = {}
    status_logs: list[MissionStatusLogSchema] = []

    model_config = ConfigDict(from_attributes=True)


class MissionDetail(MissionListItem):
    """Full mission detail including geospatial and metadata."""

    created_at: datetime
    updated_at: datetime | None = None
    status: str
    original_filename: str
    duration_seconds: float | None = None
    file_size_bytes: int | None = None
    error_message: str | None = None
    center: Location | None = None
    frame_count: int = 0
    meta: dict[str, Any] = {}
    bounding_box: dict[str, Any] | None = None  # GeoJSON-like
    point_cloud_path: str | None = None
    mesh_path: str | None = None
    orthophoto_path: str | None = None
    orthophoto_download_url: str | None = None
    point_cloud_download_url: str | None = None
    mesh_download_url: str | None = None
    dsm_path: str | None = None
    status_logs: list[MissionStatusLogSchema] = []


class FrameListItem(BaseModel):
    """Lightweight frame for list views."""

    id: int
    mission_id: int
    relative_time_seconds: float | None = None
    frame_number: int | None = None
    location: Location | None = None
    altitude_m: float | None = None
    gimbal_pitch_deg: float | None = None
    vegetation_index: float | None = None
    thumbnail_path: str | None = None
    frame_path: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FrameDetail(FrameListItem):
    """Full frame detail with timestamp and full analysis metadata."""

    frame_timestamp: datetime
    frame_path: str | None = None
    analysis_metadata: dict[str, Any] = {}


class PaginatedMissions(BaseModel):
    """Standard paged response for missions."""

    total: int
    items: list[MissionListItem]


class PaginatedFrames(BaseModel):
    """Standard paged response for frames."""

    total: int
    items: list[FrameListItem]
