from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy.orm import Session

from birdseye.db.models import Frame, Mission


def test_trigger_orthomosaic_schedules_background_task(client: TestClient, db: Session):
    """Test that triggering orthomosaic adds generate_orthomosaic to background tasks."""
    # Create a minimal mission
    mission = Mission(
        original_filename="test_for_ortho.tif",
        status="frames_extracted",
        meta={},
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    with patch("birdseye.api.v1.routers.missions.generate_orthomosaic") as mock_generate:
        response = client.post(f"/api/v1/missions/{mission.id}/orthomosaic")

        assert response.status_code == 202
        assert response.json()["status"] == "queued"

        # Verify that generate_orthomosaic was scheduled
        mock_generate.assert_called_once()
        args, kwargs = mock_generate.call_args
        assert args[0] == int(mission.id)  # first arg is mission_id


@patch("birdseye.tasks.processing.Node")
def test_generate_orthomosaic_calls_odm(mock_node_class, db: Session):
    mission = Mission(
        original_filename="test_odm.tif",
        status="frames_extracted",
        meta={},
    )
    db.add(mission)
    db.flush()

    base_time = datetime.utcnow()

    for i in range(3):
        frame = Frame(
            mission_id=mission.id,
            frame_timestamp=base_time + timedelta(seconds=i * 2),
            frame_number=i,
            relative_time_seconds=i * 2.0,
            location=from_shape(Point(-87.95 + i * 0.001, 41.727 + i * 0.001), srid=4326),
        )
        db.add(frame)

    db.commit()
    db.refresh(mission)
