"""
api/main.py — FMEA Platform FastAPI application.

Start with:
    uvicorn api.main:app --reload --port 8000

OpenAPI docs: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import eval as eval_router
from api.routers import github as github_router
from api.routers import remediation, scan, scoring as scoring_router, telemetry as telemetry_router, workspace

app = FastAPI(
    title="FMEA Platform API",
    version="1.0.0",
    description="AI-native continuous Failure Mode & Effects Analysis for software teams.",
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

app.include_router(scan.router)
app.include_router(workspace.router)
app.include_router(remediation.router)
app.include_router(eval_router.router)
app.include_router(github_router.router)
app.include_router(telemetry_router.router)
app.include_router(scoring_router.router)


@app.get("/api/health")
async def health():
    """Liveness probe."""
    return {"status": "ok"}
