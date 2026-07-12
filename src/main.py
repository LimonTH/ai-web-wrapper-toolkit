import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from src.__version__ import __version__
from src.core.config import settings
from src.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and settings service on startup."""
    await init_db()
    from src.core.database import async_session_factory
    from src.core.settings_service import get_settings_service

    svc = get_settings_service()
    async with async_session_factory() as db:
        await svc.reload(db)

    yield

app = FastAPI(
    title="AI Web Wrapper Toolkit",
    description="Turn any AI website into an OpenAI-compatible API",
    version=__version__,
    lifespan=lifespan,
)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """Human-readable validation errors."""
    errors = exc.errors()
    messages = []
    for err in errors:
        field = err.get("loc", ["unknown"])[-1]
        msg = err.get("msg", "Invalid value")
        ctx = err.get("ctx", {})
        if "min_length" in ctx:
            messages.append(f"'{field}' is too short (minimum {ctx['min_length']} characters)")
        elif "pattern" in ctx:
            messages.append(f"'{field}' has invalid format")
        else:
            clean = msg.replace("Value error, ", "").replace("Input should be ", "")
            messages.append(clean)
    text = ". ".join(messages) if messages else "Validation error"
    return JSONResponse(status_code=422, content={"detail": text})


@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: HTTPException | StarletteHTTPException):
    """Clean HTTP errors — no raw details, just the message."""
    detail = exc.detail
    if isinstance(detail, str):
        text = detail
    elif isinstance(detail, list):
        parts = []
        for d in detail:
            if isinstance(d, dict):
                parts.append(d.get("msg", str(d)))
            else:
                parts.append(str(d))
        text = "; ".join(parts)
    else:
        text = str(detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": text})


static_dir = Path(__file__).parent / "ui" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


from src.providers.router import router as template_router
from src.cookie_collector.router import router as cookie_router
from src.recorder.router import router as action_router
from src.proxy.router import router as openai_router

app.include_router(template_router, prefix="/api/templates", tags=["Templates"])
app.include_router(cookie_router, prefix="/api/cookies", tags=["Cookies"])
app.include_router(action_router, prefix="/api/actions", tags=["Action Recording"])
app.include_router(openai_router, prefix="", tags=["OpenAI API"])


from src.ui.router import router as ui_router
app.include_router(ui_router, prefix="/ui", tags=["UI"])


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/")


@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version}


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
