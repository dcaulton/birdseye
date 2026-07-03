from pathlib import Path

from sqlalchemy.orm import Session

from birdseye.db.models import Mission

TEST_DATA_DIR = Path(__file__).parent / "data"


def create_mission_with_orthophoto(db: Session) -> Mission:
    """Create a test mission that points to a small real orthophoto."""
    orthophoto_path = str(TEST_DATA_DIR / "odm_orthophoto.tif")

    mission = Mission(
        original_filename="test_mission.tif",
        status="orthomosaic_completed",
        orthophoto_path=orthophoto_path,
        meta={},
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return mission
