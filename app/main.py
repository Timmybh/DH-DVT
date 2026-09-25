import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import actual, admin, auth, calendar_rules, erp_qtcn_sync, snapshots, so, dashboard, dashboard_admin, formulas, lifecycle, monitoring, planning, resources, sync, technology_process, technology_process_generator, theme
from app.core.config import ROOT_DIR, settings
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.seed import run_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dvt")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_seed()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.middleware("http")
async def security_headers(request, call_next):
    """Header bảo mật cơ bản cho mọi phản hồi (không đặt CSP vì cần script Google SSO)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


api = APIRouter(prefix="/api")
for module in (auth, admin, sync, dashboard, dashboard_admin, planning, formulas, resources, actual, lifecycle, monitoring, theme, calendar_rules, snapshots, so, technology_process, erp_qtcn_sync, technology_process_generator):
    api.include_router(module.router)


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api)


@app.get("/health")
def health_root() -> dict[str, str]:
    return {"status": "ok"}


def _find_static_dir() -> Path | None:
    candidates = [Path(settings.static_dir)] if settings.static_dir else []
    candidates += [ROOT_DIR / "static", ROOT_DIR / "frontend" / "dist"]
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


_static = _find_static_dir()
if _static is not None:
    log.info("Phục vụ frontend từ %s", _static)
    if (_static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Không tìm thấy")
        candidate = (_static / full_path).resolve()
        if full_path and candidate.is_file() and _static.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
