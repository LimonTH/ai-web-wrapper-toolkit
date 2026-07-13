import json
import time
import uuid
from typing import Any, AsyncGenerator

import httpx
from fastapi import HTTPException, status

from src.providers.config import ProviderConfig
from src.proxy.providers.registry import get_registry

"""
Agent Transformer — OpenAI-compatible proxy with config-driven provider adapters.
Accepts requests in OpenAI format and proxies them to the real web-wrapper API.
"""

_ENDPOINT_BLOCK_MAP: dict[str, str] = {
    "/v1/chat/completions": "chat",
    "/v1/images/generations": "image_gen",
    "/v1/audio/speech": "tts",
    "/v1/audio/transcriptions": "stt",
}


async def proxy_request(
    config: ProviderConfig,
    cookie_profile: Any | None,
    body: dict[str, Any],
    openai_path: str,
) -> dict[str, Any] | AsyncGenerator[str, None]:
    """
    Proxies the request to the web-wrapper via the provider adapter.
    Supports multi-step session lifecycle:
      1. adapter.prepare_session(body)  — once per conversation
      2. adapter.build_payload(...)     — every request
      3. adapter.extract_meta(...)      — every response
    Returns a dict for sync responses or an AsyncGenerator for streaming.
    """
    block = _ENDPOINT_BLOCK_MAP.get(openai_path, "chat")

    registry = get_registry()
    adapter = registry.get_adapter(config.provider_id)

    if block not in adapter.supports:
        supported = ", ".join(sorted(adapter.supports))
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Provider '{adapter.provider_id}' does not support '{block}'. "
                   f"Supported: {supported}",
        )

    # Build URL from config
    url = config.get_endpoint_url(block)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Endpoint '{block}' not configured for provider '{config.provider_id}'. "
                   f"Add it to data/providers/{config.provider_id}.yaml",
        )

    stream = body.get("stream", False)
    headers = adapter.get_headers(block, stream=stream)

    # ── Attach cookies from cookie profile ─────────────────────────
    if cookie_profile:
        if getattr(cookie_profile, "extra_headers", None):
            headers.update(cookie_profile.extra_headers)
        # Convert Playwright-format cookies to Cookie header if not already set
        cookies_list = getattr(cookie_profile, "cookies", None)
        if cookies_list and "Cookie" not in headers:
            cookie_str = "; ".join(
                f"{c['name']}={c['value']}"
                for c in cookies_list
                if isinstance(c, dict) and "name" in c and "value" in c
            )
            if cookie_str:
                headers["Cookie"] = cookie_str

    # ── Multi-step session init (once per conversation) ───────────
    # NOTE: called AFTER headers are built, so cookies are available
    if not adapter.session:
        session_vars = await adapter.prepare_session(body, headers=headers)
        adapter.session.update(session_vars)

    payload = adapter.build_payload(block, body, block=block)
    model_id = body.get("model", adapter.get_model_id(config.provider_id))

    async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code >= 400:
            error_text = response.text[:1000]
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Upstream API error ({url}): {error_text}",
            )

        # ── Extract meta from response headers ──────────────────
        meta = adapter.extract_meta(dict(response.headers), None)
        adapter.session.update(meta)

        if stream:
            return _proxy_stream(
                response=response, model=model_id, adapter=adapter, block=block,
            )

        return await _proxy_sync(
            response=response, model=model_id, adapter=adapter, block=block,
        )


async def _proxy_sync(
    response: httpx.Response,
    model: str, adapter, block: str = "chat",
) -> dict[str, Any]:
    # Detect RSC / custom text formats (v0 returns text/plain or text/x-component)
    ctype = response.headers.get("content-type", "")
    if "text/plain" in ctype or "text/x-component" in ctype:
        # Full raw text — adapter.extract_content handles RSC decoding
        content = adapter.extract_content(response.text, block=block)
        if block == "image_gen":
            return _build_openai_image_response(model=model, data=response.text, adapter=adapter, block=block)
        if block == "tts":
            return {"audio": content, "model": model}
        return _build_openai_response(model=model, content=content)

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
    response: httpx.Response,
    model: str, adapter, block: str = "chat",
) -> AsyncGenerator[str, None]:
    yield _build_openai_chunk(model=model, content="")

    # Check if adapter overrides streaming (e.g. v0 with RSC)
    # Use a flag to avoid calling hasattr on every line
    adapter_owns_stream = hasattr(adapter, 'handle_stream') and callable(adapter.handle_stream)
    if adapter_owns_stream:
        async for chunk in adapter.handle_stream(response, model, block):
            yield chunk
        return

    async for line in response.aiter_lines():
        stripped = line.strip()
        if not stripped:
            continue
        # SSE data: prefix or JSON object/array start
        if not stripped.startswith("data:") and not stripped.startswith("{") and not stripped.startswith("["):
            continue

        raw = stripped.removeprefix("data:").strip()
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


def get_model_id(config: ProviderConfig) -> str:
    return config.provider_id.lower().replace(" ", "-").replace("_", "-")


def get_model_ids(config: ProviderConfig) -> list[str]:
    base_id = get_model_id(config)
    supports = config.supports or {"chat"}
    return [f"{base_id}/{block}" for block in sorted(supports)]


async def get_available_models(config: ProviderConfig) -> list[dict[str, str]]:
    """Returns models for the provider config — uses adapter if available."""
    from src.proxy.providers.registry import get_registry

    registry = get_registry()
    adapter = registry.get_adapter(config.provider_id)
    # Use adapter's get_model_ids() — it may return real model names (e.g. v0-max)
    model_ids = adapter.get_model_ids(config.provider_id)
    now = int(time.time())
    return [
        {
            "id": mid,
            "object": "model",
            "created": now,
            "owned_by": config.base_url,
        }
        for mid in model_ids
    ]


async def get_all_models_from_configs() -> list[dict[str, str]]:
    """Models of all known provider configs — uses adapters for real model names."""
    from src.providers.config import load_all_provider_configs
    from src.proxy.providers.registry import get_registry

    registry = get_registry()
    configs = load_all_provider_configs()
    all_models: list[dict[str, str]] = []
    for config in configs.values():
        adapter = registry.get_adapter(config.provider_id)
        model_ids = adapter.get_model_ids(config.provider_id)
        now = int(time.time())
        all_models.extend([
            {
                "id": mid,
                "object": "model",
                "created": now,
                "owned_by": config.base_url,
            }
            for mid in model_ids
        ])
    return all_models
