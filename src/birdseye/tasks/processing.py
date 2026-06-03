"""
Background processing tasks.
"""

from pathlib import Path
import shutil

from ..db.session import SessionLocal
from ..db.models import Mission


STORAGE_ROOT = Path("/data/birdseye")


def process_uploaded_video(mission_id: int, upload_file):
    db = SessionLocal()
    try:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission:
            return

        mission.status = "processing"
        db.commit()

        # Save file
        dest_dir = STORAGE_ROOT / f"missions/{mission_id}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / upload_file.filename

        with open(dest_path, "wb") as f:
            shutil.copyfileobj(upload_file.file, f)

        mission.metadata = {"original_file_path": str(dest_path)}
        mission.status = "completed"
        db.commit()

    except Exception as e:
        if mission:
            mission.status = "failed"
            mission.error_message = str(e)
            db.commit()
    finally:
        db.close()
