"""
birdseye FastAPI application entrypoint.
"""

import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from birdseye.core.config import settings

from .api.v1.routers.missions import router as v1_missions_router
from .db.models import Mission
from .db.session import get_db, init_db
from .tasks.processing import process_uploaded_video


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()  # dev convenience; use Alembic in prod
    yield


app = FastAPI(title="birdseye", version="0.1.0", lifespan=lifespan)

# Versioned API following project conventions (easy to add /v2 later)
app.include_router(v1_missions_router, prefix="/api/v1")

app.mount("/data", StaticFiles(directory=settings.storage_root), name="data")


@app.post("/upload", status_code=202)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    srt_file: Annotated[UploadFile | None, File()] = None,
    sample_interval_sec: Annotated[float, Query(ge=0.5, le=10.0)] = 2.0,
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith((".mp4", ".mov")):
        raise HTTPException(status_code=400, detail="Only MP4/MOV files supported")

    mission = Mission(original_filename=file.filename, status="pending")
    db.add(mission)
    db.commit()
    db.refresh(mission)

    # Persist uploads to temp files
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
        int(mission.id),
        tmp_video_path,
        file.filename,
        tmp_srt_path,
        None,  # db (will be created inside the task)
        sample_interval_sec,  # ← pass it through
    )

    return {"mission_id": mission.id, "status": "pending"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
