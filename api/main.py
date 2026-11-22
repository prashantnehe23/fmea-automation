"""
api/main.py — FMEA Platform FastAPI application.

Start with:
    uvicorn api.main:app --reload --port 8000

OpenAPI docs: http://localhost:8000/docs
"""

import logging
import os
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from api.policy import enforce
from api.routers import auth as auth_router
from api.routers import ci as ci_router
from api.routers import imports as imports_router
from api.routers import eval as eval_router
from api.routers import findings as findings_router
from api.routers import github as github_router
from api.routers import chat as chat_router
from api.routers import remediation, scan, scoring as scoring_router, settings as settings_router, telemetry as telemetry_router, workspace


def _bg_refresh_pricing() -> None:
    try:
        from core.costs import refresh_pricing
        refresh_pricing()
    except Exception:
        pass


from core.version import APP_VERSION

app = FastAPI(
    title="FMEA Platform API",
    version=APP_VERSION,
    description="AI-native continuous Failure Mode & Effects Analysis for software teams.",
    dependencies=[Depends(enforce)],
    # The schema pages are not covered by the session check; keep them off unless explicitly enabled
    docs_url="/docs" if os.environ.get("FMEA_API_DOCS") == "1" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if os.environ.get("FMEA_API_DOCS") == "1" else None,      # B-015: every route needs a session unless api/policy.py says public
)

# Allow requests from the React dev server and any local production build
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server
        "http://localhost:4173",   # Vite preview
        "http://localhost:3000",   # fallback
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(scan.router)
app.include_router(ci_router.router)
app.include_router(imports_router.router)
app.include_router(findings_router.router)
app.include_router(workspace.router)
app.include_router(remediation.router)
app.include_router(eval_router.router)
app.include_router(github_router.router)
app.include_router(telemetry_router.router)
app.include_router(scoring_router.router)
app.include_router(settings_router.router)
app.include_router(chat_router.router)


@app.on_event("startup")
async def startup() -> None:
    from core.secrets import encrypt_stored_keys
    from core.retention import purge_now, start_background_purge
    from core.auth import bootstrap_admin_from_env
    bootstrap_admin_from_env()
    encrypt_stored_keys()                       # raises with a clear message if FMEA_SECRET_KEY is invalid
    try:
        purge_now()
    except Exception:
        logging.getLogger(__name__).warning("startup source purge failed", exc_info=True)
    start_background_purge()
    threading.Thread(target=_bg_refresh_pricing, daemon=True).start()


@app.get("/api/health")
async def health():
    """Liveness and readiness: version, database status and how provider keys are stored (B-042)."""
    import memory.db as db
    from core.secrets import key_storage, undecryptable_providers
    try:
        conn = db.get_db()
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        database = "ok"
    except Exception:
        database = "error"
    body = {"status": "ok" if database == "ok" else "degraded", "version": APP_VERSION,
            "database": database, "key_storage": key_storage(),
            "undecryptable_keys": undecryptable_providers()}
    return JSONResponse(body, status_code=200 if database == "ok" else 503)


# Built frontend (container image): FMEA_STATIC_DIR points at frontend/dist. API routes above win.
_static = os.environ.get("FMEA_STATIC_DIR", "").strip()
if _static and (Path(_static) / "index.html").is_file():
    _static_root = Path(_static).resolve()
    if (_static_root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_static_root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        try:
            candidate = (_static_root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(_static_root):
                return FileResponse(candidate)
        except (ValueError, OSError):
            pass                                  # odd paths fall through to the app shell
        return FileResponse(_static_root / "index.html")
