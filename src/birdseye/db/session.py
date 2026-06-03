"""
Database session management for birdseye.

Matches the pattern used in sound-detection.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

# TODO: load from settings / environment
DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/birdseye"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables (development only). Use Alembic for production."""
    Base.metadata.create_all(bind=engine)
