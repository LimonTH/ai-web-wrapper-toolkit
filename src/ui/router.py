import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.core.models import WebsiteTemplate, CookieProfile, VirtualApiKey, ActionRecording, ApiEndpoint
from src.core.settings_service import get_settings_service
from src.proxy.providers.registry import get_registry

"""
UI Router — server-side Jinja2 rendering + HTMX.
"""

router = APIRouter()

_jinja_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=True,
)


def _render(name: str, **context) -> str:
    return _jinja_env.get_template(name).render(**context)


def _toast(message: str, type_: str = "success") -> dict[str, str]:
    return {"HX-Trigger": json.dumps({"showToast": {"message": message, "type": type_}})}


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    providers = get_registry().list_providers()
    p_count = len(providers)
    c_count = len((await db.execute(select(CookieProfile))).scalars().all())
    k_count = len((await db.execute(select(VirtualApiKey))).scalars().all())
    return _render(
        "index.html",
        request=request,
        active="dashboard",
        stats={"providers": p_count, "cookies": c_count, "keys": k_count},
    )


@router.get("/providers", response_class=HTMLResponse)
async def providers_nav(request: Request):
    return await providers_page(request)

@router.get("/templates", response_class=HTMLResponse)
async def providers_page(request: Request):
    providers = get_registry().list_providers()
    return _render(
        "templates/list.html",
        request=request,
        active="providers",
        providers=providers,
    )


@router.get("/cookies", response_class=HTMLResponse)
async def cookies_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CookieProfile).order_by(CookieProfile.created_at.desc())
    )
    return _render(
        "cookies/list.html",
        request=request,
        active="cookies",
        profiles=list(result.scalars().all()),
    )


@router.get("/cookies/new", response_class=HTMLResponse)
async def new_cookie_form(request: Request):
    providers = get_registry().list_providers()
    return _render(
        "partials/cookie_form.html",
        request=request,
        providers=providers,
    )


@router.get("/cookies/paste", response_class=HTMLResponse)
async def paste_cookies_form(request: Request):
    providers = get_registry().list_providers()
    return _render(
        "partials/cookie_paste.html",
        request=request,
        providers=providers,
    )


@router.get("/cookies/{profile_id}/edit", response_class=HTMLResponse)
async def edit_cookie_form(profile_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    p_result = await db.execute(select(CookieProfile).where(CookieProfile.id == profile_id))
    p = p_result.scalar_one_or_none()
    if not p:
        return _render("partials/error.html", request=request, message="Profile not found")
    t_result = await db.execute(select(WebsiteTemplate).order_by(WebsiteTemplate.name))
    return _render(
        "partials/cookie_edit.html",
        request=request,
        p=p,
        templates=list(t_result.scalars().all()),
    )


@router.get("/recorder", response_class=HTMLResponse)
async def recorder_page(request: Request, db: AsyncSession = Depends(get_db)):
    providers = get_registry().list_providers()

    c_result = await db.execute(select(CookieProfile).order_by(CookieProfile.name))
    cookie_profiles = list(c_result.scalars().all())

    r_result = await db.execute(
        select(ActionRecording)
        .options(selectinload(ActionRecording.actions))
        .order_by(ActionRecording.created_at.desc()).limit(20)
    )
    recordings = list(r_result.scalars().all())

    return _render(
        "recorder/index.html",
        request=request,
        active="recorder",
        providers=providers,
        cookie_profiles=cookie_profiles,
        recordings=recordings,
    )


@router.get("/keys", response_class=HTMLResponse)
async def keys_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(VirtualApiKey).order_by(VirtualApiKey.created_at.desc())
    )
    return _render(
        "keys/list.html",
        request=request,
        active="keys",
        keys=list(result.scalars().all()),
    )


@router.get("/keys/new", response_class=HTMLResponse)
async def new_key_form(request: Request, db: AsyncSession = Depends(get_db)):
    providers = get_registry().list_providers()
    c_result = await db.execute(select(CookieProfile).order_by(CookieProfile.name))
    return _render(
        "partials/key_form.html",
        request=request,
        providers=providers,
        cookie_profiles=list(c_result.scalars().all()),
    )


@router.get("/cookies/by-template", response_class=HTMLResponse)
async def cookie_profiles_by_template(
        request: Request,
        db: AsyncSession = Depends(get_db),
        template_id: str = Query(""),
):
    """HTML partial: list of cookie profiles for a specific template."""
    if not template_id:
        return _render("partials/cookie_options.html", request=request, profiles=[])

    result = await db.execute(
        select(CookieProfile)
        .where(CookieProfile.template_id == template_id)
        .order_by(CookieProfile.name)
    )
    profiles = list(result.scalars().all())

    if not profiles:
        t_result = await db.execute(
            select(WebsiteTemplate).where(WebsiteTemplate.name == template_id)
        )
        template = t_result.scalar_one_or_none()
        if template:
            result = await db.execute(
                select(CookieProfile)
                .where(CookieProfile.template_id == template.id)
                .order_by(CookieProfile.name)
            )
            profiles = list(result.scalars().all())

    return _render("partials/cookie_options.html", request=request, profiles=profiles)


@router.get("/api", response_class=HTMLResponse)
async def api_inspector_page(request: Request, db: AsyncSession = Depends(get_db)):
    """API Inspector: list all templates with their endpoint counts."""
    t_result = await db.execute(
        select(WebsiteTemplate).order_by(WebsiteTemplate.name)
    )
    templates = list(t_result.scalars().all())

    for t in templates:
        ep_result = await db.execute(
            select(func.count(ApiEndpoint.id)).where(ApiEndpoint.template_id == t.id)
        )
        t.endpoints_count = ep_result.scalar() or 0

    c_result = await db.execute(select(CookieProfile).order_by(CookieProfile.name))
    cookie_profiles = list(c_result.scalars().all())

    return _render(
        "api/list.html",
        request=request,
        active="api",
        templates=templates,
        cookie_profiles=cookie_profiles,
    )


@router.get("/api/{template_id}", response_class=HTMLResponse)
async def api_template_detail(
        template_id: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
):
    """API Inspector detail: view endpoints for a specific template."""
    t_result = await db.execute(
        select(WebsiteTemplate).where(WebsiteTemplate.id == template_id)
    )
    template = t_result.scalar_one_or_none()
    if not template:
        return _render("partials/error.html", request=request, message=f"Template {template_id} not found")

    ep_result = await db.execute(
        select(ApiEndpoint)
        .where(ApiEndpoint.template_id == template_id)
        .order_by(ApiEndpoint.order, ApiEndpoint.created_at)
    )
    endpoints = list(ep_result.scalars().all())

    return _render(
        "api/detail.html",
        request=request,
        active="api",
        template=template,
        endpoints=endpoints,
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    from src.core.settings_service import get_settings_service
    svc = get_settings_service()
    ui_settings = await svc.get_ui_settings(db)
    return _render(
        "settings.html",
        request=request,
        active="settings",
        proxy_url=ui_settings.get("proxy_url", ""),
        proxy_scope=ui_settings.get("proxy_scope", "none"),
        playwright_browser=ui_settings.get("playwright_browser", "chromium"),
    )


@router.post("/settings/save")
async def save_settings(request: Request, db: AsyncSession = Depends(get_db)):
    """Saves settings to DB — toast on success/error via HX-Trigger."""

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            content={"status": "error"},
            status_code=400,
            headers=_toast("Invalid JSON in request body", "error"),
        )

    svc = get_settings_service()
    await svc.set("proxy_url", body.get("proxy_url", ""), db)
    await svc.set("proxy_scope", body.get("proxy_scope", "none"), db)
    await svc.set("playwright_browser", body.get("playwright_browser", "chromium"), db)
    await svc.reload(db)
    return JSONResponse(
        content={"status": "ok"},
        headers=_toast("Settings saved — applied immediately"),
    )
