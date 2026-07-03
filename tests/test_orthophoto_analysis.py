from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from birdseye.db.models import Mission
from birdseye.tasks.processing import analyze_orthophoto
from tests.helpers import create_mission_with_orthophoto


def test_analyze_orthophoto_populates_stats(db: Session):
    """Basic test: analysis should compute and store vegetation stats."""
    mission = create_mission_with_orthophoto(db)

    analyze_orthophoto(int(mission.id), db)
    db.refresh(mission)

    assert "vegetation" in mission.meta
    veg = mission.meta["vegetation"]

    assert "mean_exg" in veg
    assert "vegetation_percent" in veg
    assert isinstance(veg["mean_exg"], float)
    assert veg["vegetation_percent"] >= 0


def test_debug_analyze_orthophoto_endpoint(client: TestClient, db: Session):
    """Test the debug endpoint returns vegetation stats."""
    mission = create_mission_with_orthophoto(db)

    response = client.post(f"/api/v1/missions/{mission.id}/debug/analyze-orthophoto")
    assert response.status_code == 200

    data = response.json()
    assert data["mission_id"] == mission.id
    assert "vegetation_stats" in data
    assert "mean_exg" in data["vegetation_stats"]


def test_analyze_orthophoto_skips_when_no_orthophoto(db: Session):
    """Should not crash when mission has no orthophoto."""
    mission = Mission(
        original_filename="no_ortho.tif",
        status="pending",
        meta={},
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    # Should not raise
    analyze_orthophoto(int(mission.id), db)


def test_mission_detail_includes_asset_paths_and_download_urls(client: TestClient, db: Session):
    """Asset paths and download URLs should be present in MissionDetail."""
    mission = create_mission_with_orthophoto(db)

    response = client.get(f"/api/v1/missions/{mission.id}")
    assert response.status_code == 200
    data = response.json()

    # Paths
    assert data["orthophoto_path"] is not None
    assert data["point_cloud_path"] is None  # not set on this test mission
    assert data["mesh_path"] is None

    # Download URLs (should be constructed from asset_base_url)
    assert data["orthophoto_download_url"] is not None
    assert data["orthophoto_download_url"].startswith("http://localhost:8001/data")


def test_analyze_orthophoto_graceful_failure_on_missing_file(db: Session):
    """Should handle missing orthophoto file without crashing hard."""
    mission = Mission(
        original_filename="bad_path.tif",
        status="orthomosaic_completed",
        orthophoto_path="nonexistent/path/to/orthophoto.tif",
        meta={},
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    # Should raise a clear exception (we can choose to catch it in the endpoint)
    with pytest.raises(Exception):  # noqa: B017
        analyze_orthophoto(int(mission.id), db)


def test_trigger_orthomosaic_passes_sample_interval(client: TestClient, db: Session):
    """sample_interval_sec should be passed through to generate_orthomosaic."""
    mission = Mission(
        original_filename="sampling_test.tif",
        status="frames_extracted",
        meta={},
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    with patch("birdseye.api.v1.routers.missions.generate_orthomosaic") as mock_generate:
        response = client.post(f"/api/v1/missions/{mission.id}/orthomosaic?sample_interval_sec=1.5")
        assert response.status_code == 202

        mock_generate.assert_called_once()
        # Check that sample_interval_sec was passed as second argument
        args, kwargs = mock_generate.call_args
        assert args[0] == mission.id
        assert args[1] == 1.5  # sample_interval_sec
