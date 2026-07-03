from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from birdseye.db.models import Mission
from tests.helpers import create_mission_with_orthophoto


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
    """Test that generate_orthomosaic actually talks to ODM."""
    mission = create_mission_with_orthophoto(db)  # or any mission with frames

    # Mock the ODM task
    mock_task = MagicMock()
    mock_task.uuid = "fake-task-123"
    mock_node = MagicMock()
    mock_node.create_task.return_value = mock_task
    mock_node_class.return_value = mock_node

    from birdseye.tasks.processing import generate_orthomosaic

    generate_orthomosaic(int(mission.id))

    mock_node.create_task.assert_called_once()
