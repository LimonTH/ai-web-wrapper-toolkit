"""
Agent Transformer — OpenAI-compatible proxy with multimodal provider adapters.
Accepts requests in OpenAI format and proxies them to the real web-wrapper API.
"""
import json
import time
import uuid
from typing import Any, AsyncGenerator

import httpx
from fastapi import HTTPException, status

from src.core.models import WebsiteTemplate, CookieProfile
from src.proxy.providers.registry import get_registry


_ENDPOINT_BLOCK_MAP: dict[str, str] = {
    "/v1/chat/completions": "chat",
    "/v1/images/generations": "image_gen",
    "/v1/audio/speech": "tts",
    "/v1/audio/transcriptions": "stt",
}


async def proxy_request(
    template: WebsiteTemplate,
    cookie_profile: CookieProfile | None,
    body: dict[str, Any],
    openai_path: str,
) -> dict[str, Any] | AsyncGenerator[str, None]:
    """
    Proxies the request to the web-wrapper via the provider adapter.
    Returns a dict for sync responses or an AsyncGenerator for streaming.
    """
    block = _ENDPOINT_BLOCK_MAP.get(openai_path, "chat")

    registry = get_registry()
    adapter = registry.get_adapter(template)

    if block not in adapter.supports:
        supported = ", ".join(sorted(adapter.supports))
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Provider '{adapter.provider_id}' does not support '{block}'. "
                   f"Supported: {supported}",
        )

    method = "POST"
    endpoint = adapter.get_endpoint(template, block=block, method=method)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Endpoint for '{block}' not configured for template '{template.name}'. "
                   f"Add an endpoint with functional_block='{block}' first.",
        )

    url = f"{template.base_url.rstrip('/')}{endpoint.path}"
    stream = body.get("stream", False)

    headers = adapter.get_headers(template, stream=stream, block=block)
    if cookie_profile and cookie_profile.extra_headers:
        headers.update(cookie_profile.extra_headers)

    payload = adapter.build_payload(endpoint, body, block=block)
    model_id = body.get("model", adapter.get_model_id(template))

    if stream:
        return _proxy_stream(
            url=url, headers=headers, payload=payload,
            model=model_id, adapter=adapter, block=block,
        )
    else:
        async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            return await _proxy_sync(
                client=client, url=url, headers=headers, payload=payload,
                model=model_id, adapter=adapter, block=block,
            )


async def _proxy_sync(
    client: httpx.AsyncClient,
    url: str, headers: dict[str, str], payload: dict[str, Any],
    model: str, adapter, block: str = "chat",
) -> dict[str, Any]:
    response = await client.post(url, headers=headers, json=payload)

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Upstream API error: {response.text[:500]}",
        )

    try:
        upstream_data = response.json()
    except json.JSONDecodeError:
        upstream_data = {"text": response.text[:500]}

    content = adapter.extract_content(upstream_data, block=block)

    if block == "image_gen":
        return _build_openai_image_response(model=model, data=upstream_data, adapter=adapter, block=block)
    if block == "tts":
        return {"audio": content, "model": model}

    return _build_openai_response(model=model, content=content)


async def _proxy_stream(
    url: str, headers: dict[str, str], payload: dict[str, Any],
    model: str, adapter, block: str = "chat",
) -> AsyncGenerator[str, None]:
    async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code >= 400:
                error_text = await response.aread()
                yield f"data: {json.dumps({'error': error_text.decode()[:500]})}\n\n"
                yield "data: [DONE]\n\n"
                return

            yield _build_openai_chunk(model=model, content="")

            async for line in response.aiter_lines():
                if not line.startswith("data:") and not line.startswith("{"):
                    continue

                raw = line.removeprefix("data:").strip()
                try:
                    upstream_chunk = json.loads(raw)
                    content = adapter.extract_stream_chunk(upstream_chunk, block=block)
                    if content:
                        yield _build_openai_chunk(model=model, content=content)
                except json.JSONDecodeError:
                    pass

            yield _build_openai_chunk(model=model, finish_reason="stop")
            yield "data: [DONE]\n\n"


def _build_openai_response(
    model: str, content: str, finish_reason: str = "stop",
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _build_openai_image_response(
    model: str, data: Any, adapter, block: str,
) -> dict[str, Any]:
    content = adapter.extract_content(data, block=block)
    return {
        "created": int(time.time()),
        "data": [{"url": content}],
    }


def _build_openai_chunk(
    model: str, content: str | None = None, finish_reason: str | None = None,
) -> str:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if finish_reason:
        delta["role"] = "assistant"

    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


async def get_available_models(template: WebsiteTemplate) -> list[dict[str, str]]:
    """Returns models for the template via the adapter."""
    registry = get_registry()
    adapter = registry.get_adapter(template)
    model_ids = adapter.get_model_ids(template)
    now = int(time.time())

    return [
        {
            "id": mid,
            "object": "model",
            "created": now,
            "owned_by": template.base_url,
        }
        for mid in model_ids
    ]


async def get_all_models(db) -> list[dict[str, str]]:
    """Models of all active templates."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(WebsiteTemplate)
        .options(selectinload(WebsiteTemplate.endpoints))
        .where(WebsiteTemplate.is_active == True)
    )
    templates = result.scalars().all()

    all_models: list[dict[str, str]] = []
    for t in templates:
        models = await get_available_models(t)
        all_models.extend(models)

    return all_models