"""
birdseye FastAPI application entrypoint.
"""

import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .db.models import Mission
from .db.session import get_db, init_db
from .tasks.processing import process_uploaded_video


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()  # dev convenience; use Alembic in prod
    yield


app = FastAPI(title="birdseye", version="0.1.0", lifespan=lifespan)


@app.post("/upload", status_code=202)  # type: ignore[misc]
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),  # noqa: B008
    srt_file: UploadFile | None = File(None),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith((".mp4", ".mov")):
        raise HTTPException(status_code=400, detail="Only MP4/MOV files supported")

    mission = Mission(original_filename=file.filename, status="pending")
    db.add(mission)
    db.commit()
    db.refresh(mission)

    # Persist uploads to temp files first (BackgroundTasks-safe)
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp_video:
        shutil.copyfileobj(file.file, tmp_video)
        tmp_video_path = tmp_video.name

    tmp_srt_path = None
    if srt_file and srt_file.filename:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".SRT") as tmp_srt:
            shutil.copyfileobj(srt_file.file, tmp_srt)
            tmp_srt_path = tmp_srt.name

    background_tasks.add_task(
        process_uploaded_video,
        mission.id,
        tmp_video_path,
        file.filename,
        tmp_srt_path,
    )

    return {"mission_id": mission.id, "status": "pending"}


@app.get("/health")  # type: ignore[misc]
def health() -> dict[str, str]:
    return {"status": "ok"}
