import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.cookie_collector.service import (
    get_all_profiles,
    get_profile_by_id,
    create_profile,
    update_profile,
    delete_profile,
    run_browser_login,
    test_cookies,
)
from src.core.database import get_db
from src.core.schemas import CookieProfileCreate, CookieProfileUpdate, CookieProfileRead

router = APIRouter()


def _toast(message: str, type_: str = "success") -> dict[str, str]:
    return {"HX-Trigger": json.dumps({"showToast": {"message": message, "type": type_}})}


@router.get("", response_model=list[CookieProfileRead])
async def list_profiles(db: AsyncSession = Depends(get_db)):
    return await get_all_profiles(db)


@router.post("", response_model=CookieProfileRead, status_code=201)
async def create_profile_endpoint(
        data: CookieProfileCreate,
        db: AsyncSession = Depends(get_db),
):
    return await create_profile(db, data)


@router.get("/{profile_id}", response_model=CookieProfileRead)
async def get_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    return await get_profile_by_id(db, profile_id)


@router.put("/{profile_id}", response_model=CookieProfileRead)
async def update_profile_endpoint(
        profile_id: str,
        data: CookieProfileUpdate,
        db: AsyncSession = Depends(get_db),
):
    return await update_profile(db, profile_id, data)


@router.delete("/{profile_id}")
async def delete_profile_endpoint(profile_id: str, db: AsyncSession = Depends(get_db)):
    await delete_profile(db, profile_id)
    return JSONResponse(
        content={"status": "deleted"},
        headers=_toast("Profile deleted"),
    )


@router.post("/{profile_id}/login")
async def login(
        profile_id: str,
        headless: bool = Query(False),
        auto_close: bool = Query(True, description="Auto-close browser after login detected"),
        db: AsyncSession = Depends(get_db),
):
    """Opens a browser for manual login."""
    profile = await run_browser_login(db, profile_id, headless=headless, auto_close=auto_close)
    cookies_count = len(profile.cookies) if profile.cookies else 0
    msg = f"Login complete: {cookies_count} cookies captured"
    toast_type = "success" if cookies_count > 0 else "warning"
    return JSONResponse(
        content={"status": "ok", "cookies_count": cookies_count},
        headers=_toast(msg, toast_type),
    )


@router.post("/{profile_id}/test")
async def test(
        profile_id: str,
        headless: bool = Query(True),
        db: AsyncSession = Depends(get_db),
):
    """Tests cookies — opens the site with injected cookies."""
    result = await test_cookies(db, profile_id, headless=headless)
    return JSONResponse(
        content=result,
        headers=_toast(result.get("message", "Test completed")),
    )
