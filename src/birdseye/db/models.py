"""
SQLAlchemy models for birdseye.
"""

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import JSON, BigInteger, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Mission(Base):
    __tablename__ = "missions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    original_filename = Column(String(255), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Geospatial
    bounding_box = Column(Geometry("POLYGON", srid=4326), nullable=True)  # type: ignore[var-annotated]
    center_point = Column(Geometry("POINT", srid=4326), nullable=True)  # type: ignore[var-annotated]

    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    error_message = Column(Text, nullable=True)
    meta = Column(JSON, default=dict)

    frames = relationship("Frame", back_populates="mission", cascade="all, delete-orphan")

    # === Orthomosaic / 2D outputs ===
    orthophoto_path: Mapped[str | None] = mapped_column(String, nullable=True)
    dsm_path: Mapped[str | None] = mapped_column(String, nullable=True)

    # === Point cloud outputs ===
    point_cloud_path: Mapped[str | None] = mapped_column(String, nullable=True)
    mesh_path: Mapped[str | None] = mapped_column(String, nullable=True)

    status_logs: Mapped[list["MissionStatusLog"]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )


class MissionStatusLog(Base):
    __tablename__ = "mission_status_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    mission: Mapped["Mission"] = relationship(back_populates="status_logs")


class Frame(Base):
    __tablename__ = "frames"

    id = Column(Integer, primary_key=True, index=True)
    mission_id = Column(Integer, ForeignKey("missions.id"), nullable=False, index=True)

    frame_timestamp = Column(DateTime, nullable=False)
    frame_number = Column(Integer, nullable=True)
    relative_time_seconds = Column(Float, nullable=True)

    location = Column(Geometry("POINT", srid=4326), nullable=True)  # type: ignore[var-annotated]
    altitude_m = Column(Float, nullable=True)
    gimbal_pitch_deg = Column(Float, nullable=True)

    frame_path = Column(String(512), nullable=True)
    thumbnail_path = Column(String(512), nullable=True)

    vegetation_index = Column(Float, nullable=True)
    analysis_metadata = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)

    mission = relationship("Mission", back_populates="frames")
