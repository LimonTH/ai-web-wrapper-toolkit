from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.schemas import ActionRecordingRead
from src.recorder.service import (
    start_recording,
    get_recording,
    get_recordings_by_template,
    export_recording_json,
)

router = APIRouter()


@router.post("/{template_id}/record", response_model=dict)
async def record_actions_endpoint(
        template_id: str,
        cookie_profile_id: str | None = Query(None),
        headless: bool = Query(False, description="Open browser in headless mode"),
        with_prompts: bool = Query(True, description="Show prompt dialogs for each action"),
        db: AsyncSession = Depends(get_db),
):
    """
    Records user actions on the website.
    Opens a browser with cookies, injects JS, saves to DB after closing.
    """
    result = await start_recording(
        db=db,
        template_id=template_id,
        cookie_profile_id=cookie_profile_id,
        headless=headless,
        with_prompts=with_prompts,
    )
    return result


@router.get("/{template_id}/recordings", response_model=list[ActionRecordingRead])
async def list_recordings(
        template_id: str,
        db: AsyncSession = Depends(get_db),
):
    return await get_recordings_by_template(db, template_id)


@router.get("/recordings/{recording_id}", response_model=ActionRecordingRead)
async def get_recording_endpoint(
        recording_id: str,
        db: AsyncSession = Depends(get_db),
):
    return await get_recording(db, recording_id)


@router.post("/recordings/{recording_id}/export")
async def export_recording_endpoint(
        recording_id: str,
        db: AsyncSession = Depends(get_db),
):
    recording = await get_recording(db, recording_id)
    filepath = await export_recording_json(recording)
    return {"recording_id": recording_id, "filepath": filepath}