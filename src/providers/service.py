from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import WebsiteTemplate, ApiEndpoint, VirtualApiKey
from src.core.schemas import (
    WebsiteTemplateCreate,
    WebsiteTemplateUpdate,
    ApiEndpointCreate,
    ApiEndpointUpdate,
    VirtualApiKeyCreate,
)
from src.providers.generator import generate_virtual_key


async def get_all_templates(db: AsyncSession) -> list[WebsiteTemplate]:
    result = await db.execute(select(WebsiteTemplate).order_by(WebsiteTemplate.created_at.desc()))
    return list(result.scalars().all())


async def get_template_by_id(db: AsyncSession, template_id: str) -> WebsiteTemplate:
    result = await db.execute(select(WebsiteTemplate).where(WebsiteTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


async def create_template(db: AsyncSession, data: WebsiteTemplateCreate) -> WebsiteTemplate:
    from src.proxy.providers.registry import get_registry
    dummy_template = type("DummyTemplate", (), {
        "name": data.name,
        "base_url": data.base_url,
        "endpoints": [],
    })()
    registry = get_registry()
    adapter = registry.get_adapter(dummy_template)
    capabilities = sorted(adapter.supports) if adapter.supports else []

    template = WebsiteTemplate(
        name=data.name,
        description=data.description,
        base_url=data.base_url,
        icon_url=data.icon_url,
        auth_type=data.auth_type,
        capabilities=capabilities,
        default_headers=data.default_headers,
    )
    db.add(template)
    await db.flush()
    return template


async def update_template(
    db: AsyncSession, template_id: str, data: WebsiteTemplateUpdate
) -> WebsiteTemplate:
    template = await get_template_by_id(db, template_id)
    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(template, field, value)
    await db.flush()
    return template


async def delete_template(db: AsyncSession, template_id: str) -> None:
    template = await get_template_by_id(db, template_id)
    await db.delete(template)
    await db.flush()


async def get_endpoints_by_template(db: AsyncSession, template_id: str) -> list[ApiEndpoint]:
    await get_template_by_id(db, template_id)
    result = await db.execute(
        select(ApiEndpoint)
        .where(ApiEndpoint.template_id == template_id)
        .order_by(ApiEndpoint.order)
    )
    return list(result.scalars().all())


async def create_endpoint(db: AsyncSession, data: ApiEndpointCreate) -> ApiEndpoint:
    await get_template_by_id(db, data.template_id)
    endpoint = ApiEndpoint(
        template_id=data.template_id,
        functional_block=data.functional_block,
        label=data.label,
        method=data.method,
        path=data.path,
        headers_template=data.headers_template,
        query_params_template=data.query_params_template,
        body_template=data.body_template,
        response_schema=data.response_schema,
        is_streaming=data.is_streaming,
        stream_event_field=data.stream_event_field,
        order=data.order,
    )
    db.add(endpoint)
    await db.flush()
    return endpoint


async def update_endpoint(
    db: AsyncSession, endpoint_id: str, data: ApiEndpointUpdate
) -> ApiEndpoint:
    result = await db.execute(select(ApiEndpoint).where(ApiEndpoint.id == endpoint_id))
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(endpoint, field, value)
    await db.flush()
    return endpoint


async def delete_endpoint(db: AsyncSession, endpoint_id: str) -> None:
    result = await db.execute(select(ApiEndpoint).where(ApiEndpoint.id == endpoint_id))
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    await db.delete(endpoint)
    await db.flush()


async def get_all_keys(db: AsyncSession) -> list[VirtualApiKey]:
    result = await db.execute(
        select(VirtualApiKey).order_by(VirtualApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def get_key_by_id(db: AsyncSession, key_id: str) -> VirtualApiKey:
    result = await db.execute(
        select(VirtualApiKey).where(VirtualApiKey.id == key_id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")
    return key


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


async def create_virtual_key(db: AsyncSession, data: VirtualApiKeyCreate) -> VirtualApiKey:
    template = await _resolve_template(db, data.template_id)

    key_data = generate_virtual_key(
        template_id=template.id,
        template_name=template.name,
        capabilities=template.capabilities,
        cookie_profile_id=data.cookie_profile_id,
        config_overrides=data.config_overrides,
        expires_at=data.expires_at,
    )

    api_key = VirtualApiKey(
        template_id=data.template_id,
        cookie_profile_id=data.cookie_profile_id,
        name=data.name,
        key_value=key_data["key_value"],
        jwt_token=key_data["jwt_token"],
        config_overrides=data.config_overrides,
        expires_at=data.expires_at,
    )
    db.add(api_key)
    await db.flush()
    return api_key


async def delete_key(db: AsyncSession, key_id: str) -> None:
    key = await get_key_by_id(db, key_id)
    await db.delete(key)
    await db.flush()