"""
OpenAI-compatible router with multimodal provider support.
Proxies requests through a provider adapter (BaseProviderAdapter).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.proxy.service import resolve_key, resolve_key_for_provider
from src.proxy.transformer import proxy_request, get_available_models, get_all_models

router = APIRouter()


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Use: Bearer wsk_live_xxx",
        )
    return auth.removeprefix("Bearer ").strip()


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, db: AsyncSession = Depends(get_db)):
    return await _proxy_openai(request, db, "/v1/chat/completions")


@router.post("/v1/images/generations")
async def image_generations(request: Request, db: AsyncSession = Depends(get_db)):
    return await _proxy_openai(request, db, "/v1/images/generations")


@router.post("/v1/audio/speech")
async def audio_speech(request: Request, db: AsyncSession = Depends(get_db)):
    return await _proxy_openai(request, db, "/v1/audio/speech")


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(request: Request, db: AsyncSession = Depends(get_db)):
    return await _proxy_openai(request, db, "/v1/audio/transcriptions")


async def _proxy_openai(request: Request, db: AsyncSession, openai_path: str):
    key_value = _extract_bearer(request)
    template, cookie_profile, _ = await resolve_key(db, key_value)
    body = await request.json()

    result = await proxy_request(
        template=template,
        cookie_profile=cookie_profile,
        body=body,
        openai_path=openai_path,
    )

    if body.get("stream", False):
        return StreamingResponse(
            result,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return result


@router.get("/v1/models")
async def list_models(request: Request, db: AsyncSession = Depends(get_db)):
    key_value = _extract_bearer(request)
    await resolve_key(db, key_value)
    models = await get_all_models(db)
    return {"object": "list", "data": models}


@router.get("/v1/{provider}/models")
async def list_provider_models(
    provider: str, request: Request, db: AsyncSession = Depends(get_db),
):
    key_value = _extract_bearer(request)
    template, _, _ = await resolve_key_for_provider(db, key_value, provider)
    models = await get_available_models(template)
    return {"object": "list", "data": models}


@router.post("/v1/{provider}/chat/completions")
async def provider_chat_completions(
    provider: str, request: Request, db: AsyncSession = Depends(get_db),
):
    return await _provider_proxy(request, db, provider, "/v1/chat/completions")


@router.post("/v1/{provider}/images/generations")
async def provider_image_generations(
    provider: str, request: Request, db: AsyncSession = Depends(get_db),
):
    return await _provider_proxy(request, db, provider, "/v1/images/generations")


@router.post("/v1/{provider}/audio/speech")
async def provider_audio_speech(
    provider: str, request: Request, db: AsyncSession = Depends(get_db),
):
    return await _provider_proxy(request, db, provider, "/v1/audio/speech")


@router.post("/v1/{provider}/audio/transcriptions")
async def provider_audio_transcriptions(
    provider: str, request: Request, db: AsyncSession = Depends(get_db),
):
    return await _provider_proxy(request, db, provider, "/v1/audio/transcriptions")


async def _provider_proxy(
    request: Request, db: AsyncSession, provider: str, openai_path: str,
):
    key_value = _extract_bearer(request)
    template, cookie_profile, _ = await resolve_key_for_provider(db, key_value, provider)
    body = await request.json()

    result = await proxy_request(
        template=template,
        cookie_profile=cookie_profile,
        body=body,
        openai_path=openai_path,
    )

    if body.get("stream", False):
        return StreamingResponse(
            result,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return result