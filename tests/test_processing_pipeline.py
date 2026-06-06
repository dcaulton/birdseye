import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from birdseye.db.models import Frame, Mission
from birdseye.tasks.processing import process_uploaded_video


def test_process_uploaded_video_full_pipeline(db: Session, monkeypatch):
    test_video = Path("data/test/test_12s_small.mp4")
    assert test_video.exists(), "Create 10s test clip first"

    srt_content = """1
00:00:00,000 --> 00:00:00,033
<font size="28">... [latitude: 41.727421] [longitude: -87.949816] [rel_alt: 2.200]</font>

2
00:00:03,000 --> 00:00:03,033
<font size="28">... [latitude: 41.727500] [longitude: -87.949900] [rel_alt: 3.100]</font>

3
00:00:06,000 --> 00:00:06,033
<font size="28">... [latitude: 41.727650] [longitude: -87.950050] [rel_alt: 4.500]</font>

4
00:00:09,000 --> 00:00:09,033
<font size="28">... [latitude: 41.727420] [longitude: -87.950100] [rel_alt: 3.800]</font>

5
00:00:12,000 --> 00:00:12,033
<font size="28">... [latitude: 41.727300] [longitude: -87.949850] [rel_alt: 2.900]</font>
"""

    srt_path = "data/test/test.srt"
    Path(srt_path).write_text(srt_content)

    mission = Mission(id=9999, original_filename="test_12s_small.mp4", status="pending")
    db.add(mission)
    db.commit()

    monkeypatch.setattr("birdseye.tasks.processing.SAMPLE_INTERVAL_SEC", 1.0)

    temp_video = Path("data/test/temp_test_video.mp4")
    shutil.copy2(test_video, temp_video)

    process_uploaded_video(
        mission_id=9999,
        tmp_video_path=str(temp_video),
        original_filename="test_12s_small.mp4",
        tmp_srt_path=srt_path,
        db=db,
    )

    mission = db.query(Mission).filter_by(id=9999).first()  # type: ignore[assignment]
    assert mission is not None
    assert mission.status == "completed"

    frames = db.query(Frame).filter_by(mission_id=9999).all()
    assert len(frames) > 0

    temp_video.unlink(missing_ok=True)
