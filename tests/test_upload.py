from unittest.mock import patch

from fastapi.testclient import TestClient


def test_upload_video(client: TestClient) -> None:
    with patch("birdseye.main.process_uploaded_video") as mock_task:
        response = client.post(
            "/upload",
            files={"file": ("test.mp4", b"fake video content", "video/mp4")},
        )

    assert response.status_code == 202
    data = response.json()
    assert "mission_id" in data
    assert data["status"] == "pending"
    mock_task.assert_called_once()
