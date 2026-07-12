from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cookie_collector.browser import login_and_get_cookies, inject_cookies_and_open
from src.core.models import CookieProfile, WebsiteTemplate
from src.core.schemas import CookieProfileCreate, CookieProfileUpdate


async def get_all_profiles(db: AsyncSession) -> list[CookieProfile]:
    result = await db.execute(
        select(CookieProfile).order_by(CookieProfile.created_at.desc())
    )
    return list(result.scalars().all())


async def get_profile_by_id(db: AsyncSession, profile_id: str) -> CookieProfile:
    result = await db.execute(
        select(CookieProfile).where(CookieProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cookie profile not found")
    return profile


async def _resolve_template(db: AsyncSession, template_id_or_name: str) -> WebsiteTemplate:
    """Finds a WebsiteTemplate by UUID or name (provider_id). Creates one if not found."""
    t_result = await db.execute(
        select(WebsiteTemplate).where(WebsiteTemplate.id == template_id_or_name)
    )
    template = t_result.scalar_one_or_none()
    if template:
        return template

    t_result = await db.execute(
        select(WebsiteTemplate).where(WebsiteTemplate.name == template_id_or_name)
    )
    template = t_result.scalar_one_or_none()
    if template:
        return template

    from src.proxy.providers.registry import get_registry
    dummy = type("DummyTemplate", (), {"name": template_id_or_name, "base_url": "", "endpoints": []})()
    registry = get_registry()
    adapter = registry.get_adapter(dummy)
    capabilities = sorted(adapter.supports) if adapter.supports else []

    url_pattern = getattr(adapter, "url_pattern", "") or ""
    base_url = f"https://{url_pattern}" if url_pattern else ""
    provider_name = getattr(adapter, "provider_name", template_id_or_name)

    template = WebsiteTemplate(
        name=template_id_or_name,
        base_url=base_url,
        description=provider_name,
        capabilities=capabilities,
    )
    db.add(template)
    await db.flush()
    return template


async def create_profile(db: AsyncSession, data: CookieProfileCreate) -> CookieProfile:
    template = await _resolve_template(db, data.template_id)

    profile = CookieProfile(
        template_id=template.id,
        name=data.name,
        description=data.description,
        cookies=data.cookies or [],
        extra_headers=data.extra_headers,
        storage_state=data.storage_state,
    )
    db.add(profile)
    await db.flush()
    return profile


async def update_profile(
        db: AsyncSession, profile_id: str, data: CookieProfileUpdate
) -> CookieProfile:
    profile = await get_profile_by_id(db, profile_id)

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(profile, field, value)

    await db.flush()
    return profile


async def delete_profile(db: AsyncSession, profile_id: str) -> None:
    profile = await get_profile_by_id(db, profile_id)
    await db.delete(profile)
    await db.flush()


async def run_browser_login(
        db: AsyncSession,
        profile_id: str,
        headless: bool = False,
        auto_close: bool = True,
) -> CookieProfile:
    """Opens a browser for manual login, collects cookies and saves to the profile."""
    profile = await get_profile_by_id(db, profile_id)

    t_result = await db.execute(
        select(WebsiteTemplate).where(WebsiteTemplate.id == profile.template_id)
    )
    template = t_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    login_url = template.base_url

    result = await login_and_get_cookies(
        template_name=template.name,
        login_url=login_url,
        headless=headless,
        auto_close=auto_close,
    )

    if result.get("logged_in"):
        profile.cookies = result["cookies"]
        profile.storage_state = result["storage_state"]
        profile.last_used_at = datetime.now(timezone.utc)
        await db.flush()
        print(f"✅ Login successful — cookies saved to profile '{profile.name}'")
    else:
        print(f"⚠️ No login detected — cookies NOT saved (existing cookies preserved)")
        profile.last_used_at = datetime.now(timezone.utc)
        await db.flush()

    return profile


async def test_cookies(
        db: AsyncSession,
        profile_id: str,
        headless: bool = True,
) -> dict:
    """Opens a browser with injected cookies for testing."""
    profile = await get_profile_by_id(db, profile_id)

    t_result = await db.execute(
        select(WebsiteTemplate).where(WebsiteTemplate.id == profile.template_id)
    )
    template = t_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if not profile.cookies:
        raise HTTPException(status_code=400, detail="No cookies in profile. Login first.")

    await inject_cookies_and_open(
        url=template.base_url,
        cookies=profile.cookies,
        storage_state=profile.storage_state,
        headless=headless,
    )

    profile.last_used_at = datetime.now(timezone.utc)
    await db.flush()

    return {"status": "ok", "message": "Browser closed after test"}
