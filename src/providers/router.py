import json
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.schemas import (
    WebsiteTemplateCreate,
    WebsiteTemplateUpdate,
    WebsiteTemplateRead,
    ApiEndpointCreate,
    ApiEndpointUpdate,
    ApiEndpointRead,
    VirtualApiKeyCreate,
    VirtualApiKeyRead,
)
from src.providers.service import (
    get_all_templates,
    get_template_by_id,
    create_template,
    update_template,
    delete_template,
    get_endpoints_by_template,
    create_endpoint,
    update_endpoint,
    delete_endpoint,
    get_all_keys,
    get_key_by_id,
    create_virtual_key,
    delete_key,
)

router = APIRouter()


# MUST be before /{template_id} to avoid "keys" matching as template_id
@router.get("/keys", response_model=list[VirtualApiKeyRead])
async def list_keys(db: AsyncSession = Depends(get_db)):
    return await get_all_keys(db)


@router.post("/keys", response_model=VirtualApiKeyRead, status_code=201)
async def create_key_endpoint(
    data: VirtualApiKeyCreate,
    db: AsyncSession = Depends(get_db),
):
    return await create_virtual_key(db, data)


@router.get("/keys/{key_id}", response_model=VirtualApiKeyRead)
async def get_key(key_id: str, db: AsyncSession = Depends(get_db)):
    return await get_key_by_id(db, key_id)


@router.delete("/keys/{key_id}")
async def delete_key_endpoint(key_id: str, db: AsyncSession = Depends(get_db)):
    await delete_key(db, key_id)
    return JSONResponse(
        content={"status": "deleted"},
        headers={"HX-Trigger": json.dumps({"showToast": {"message": "Key revoked", "type": "success"}})},
    )


@router.get("", response_model=list[WebsiteTemplateRead])
async def list_templates(db: AsyncSession = Depends(get_db)):
    return await get_all_templates(db)


@router.post("", response_model=WebsiteTemplateRead, status_code=201)
async def create_template_endpoint(
    data: WebsiteTemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    return await create_template(db, data)


@router.get("/{template_id}", response_model=WebsiteTemplateRead)
async def get_template_endpoint(template_id: str, db: AsyncSession = Depends(get_db)):
    return await get_template_by_id(db, template_id)


@router.put("/{template_id}", response_model=WebsiteTemplateRead)
async def update_template_endpoint(
    template_id: str,
    data: WebsiteTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await update_template(db, template_id, data)


@router.delete("/{template_id}", status_code=204)
async def delete_template_endpoint(template_id: str, db: AsyncSession = Depends(get_db)):
    await delete_template(db, template_id)


@router.get("/{template_id}/endpoints", response_model=list[ApiEndpointRead])
async def list_endpoints(template_id: str, db: AsyncSession = Depends(get_db)):
    return await get_endpoints_by_template(db, template_id)


@router.post("/{template_id}/endpoints", response_model=ApiEndpointRead, status_code=201)
async def create_endpoint_endpoint(
    template_id: str,
    data: ApiEndpointCreate,
    db: AsyncSession = Depends(get_db),
):
    data.template_id = template_id
    return await create_endpoint(db, data)


@router.put("/endpoints/{endpoint_id}", response_model=ApiEndpointRead)
async def update_endpoint_endpoint(
    endpoint_id: str,
    data: ApiEndpointUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await update_endpoint(db, endpoint_id, data)


@router.delete("/endpoints/{endpoint_id}", status_code=204)
async def delete_endpoint_endpoint(endpoint_id: str, db: AsyncSession = Depends(get_db)):
    await delete_endpoint(db, endpoint_id)


@router.get("/capabilities-preview")
async def capabilities_preview(url: str = Query(...)):
    """Preview capabilities for a URL based on registered provider adapters."""
    from src.proxy.providers.registry import get_registry
    if not url.startswith("http"):
        return {"capabilities": []}
    dummy = type("DummyTemplate", (), {"name": "", "base_url": url, "endpoints": []})()
    registry = get_registry()
    adapter = registry.get_adapter(dummy)
    caps = sorted(adapter.supports) if adapter.supports else []
    return {"capabilities": caps, "provider": adapter.provider_id}