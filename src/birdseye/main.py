"""
birdseye FastAPI application entrypoint.
"""

from fastapi import BackgroundTasks, FastAPI, File, UploadFile, Depends, HTTPException
from sqlalchemy.orm import Session

from .db.session import get_db, init_db
from .db.models import Mission
from .tasks.processing import process_uploaded_video

app = FastAPI(title="birdseye", version="0.1.0")


@app.on_event("startup")
def startup_event():
    init_db()


@app.post("/upload", status_code=202)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith((".mp4", ".mov")):
        raise HTTPException(status_code=400, detail="Only MP4/MOV files supported")

    mission = Mission(
        original_filename=file.filename,
        status="pending",
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    background_tasks.add_task(process_uploaded_video, mission.id, file)

    return {"mission_id": mission.id, "status": "pending"}


@app.get("/health")
def health():
    return {"status": "ok"}
