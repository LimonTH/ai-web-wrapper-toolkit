from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.models import WebsiteTemplate, CookieProfile, VirtualApiKey
from src.providers.generator import decode_virtual_key


async def resolve_key(
        db: AsyncSession, key_value: str
) -> tuple[WebsiteTemplate, CookieProfile | None, VirtualApiKey]:
    """Finds Template + CookieProfile by key value (wsk_live_xxx)."""
    v_result = await db.execute(
        select(VirtualApiKey).where(VirtualApiKey.key_value == key_value)
    )
    virtual_key = v_result.scalar_one_or_none()
    if not virtual_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    if not virtual_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key is deactivated",
        )

    t_result = await db.execute(
        select(WebsiteTemplate)
        .options(selectinload(WebsiteTemplate.endpoints))
        .where(WebsiteTemplate.id == virtual_key.template_id)
    )
    template = t_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template.is_active:
        raise HTTPException(status_code=403, detail="Template is deactivated")

    cookie_profile = None
    payload = decode_virtual_key(virtual_key.jwt_token) if virtual_key.jwt_token else None
    if payload and payload.get("cookie_profile_id"):
        c_result = await db.execute(
            select(CookieProfile).where(
                CookieProfile.id == payload["cookie_profile_id"]
            )
        )
        cookie_profile = c_result.scalar_one_or_none()

    return template, cookie_profile, virtual_key


async def resolve_key_for_provider(
        db: AsyncSession, key_value: str, provider: str
) -> tuple[WebsiteTemplate, CookieProfile | None, VirtualApiKey]:
    """Like resolve_key, but checks that the key's template matches the provider from URL."""
    template, cookie_profile, virtual_key = await resolve_key(db, key_value)
    slug = template.name.lower().replace(" ", "-").replace("_", "-")
    if slug != provider:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key is for provider '{slug}', not '{provider}'",
        )
    return template, cookie_profile, virtual_key
