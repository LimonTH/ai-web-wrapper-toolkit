from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import CookieProfile, VirtualApiKey, WebsiteTemplate
from src.providers.config import ProviderConfig
from src.providers.generator import decode_virtual_key
from src.proxy.providers.registry import get_registry


async def resolve_key(
    db: AsyncSession, key_value: str
) -> tuple[ProviderConfig, CookieProfile | None, VirtualApiKey]:
    """Finds ProviderConfig + CookieProfile by key value (wsk_live_xxx)."""
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

    # Load template just for provider_id resolution (no endpoints needed)
    t_result = await db.execute(
        select(WebsiteTemplate).where(WebsiteTemplate.id == virtual_key.template_id)
    )
    template = t_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template.is_active:
        raise HTTPException(status_code=403, detail="Template is deactivated")

    # Load ProviderConfig from YAML (single source of truth)
    config = get_registry().get_config(template.name)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Provider config '{template.name}' not found. "
                   f"Create data/providers/{template.name}.yaml first.",
        )

    cookie_profile = None
    payload = decode_virtual_key(virtual_key.jwt_token) if virtual_key.jwt_token else None
    if payload and payload.get("cookie_profile_id"):
        c_result = await db.execute(
            select(CookieProfile).where(
                CookieProfile.id == payload["cookie_profile_id"]
            )
        )
        cookie_profile = c_result.scalar_one_or_none()

    return config, cookie_profile, virtual_key


async def resolve_key_for_provider(
    db: AsyncSession, key_value: str, provider: str
) -> tuple[ProviderConfig, CookieProfile | None, VirtualApiKey]:
    """Like resolve_key, but checks that the key matches the provider from URL."""
    config, cookie_profile, virtual_key = await resolve_key(db, key_value)
    if config.provider_id != provider:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key is for provider '{config.provider_id}', not '{provider}'",
        )
    return config, cookie_profile, virtual_key
