from contextlib import asynccontextmanager
from pathlib import Path

import briefcase
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import configurations, datasets, evals, evidence, experiments, golden, library
from app.api import settings as settings_api
from app.config import ROOT, settings
from app.db import create_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db()
    yield


app = FastAPI(title="OutputTracker API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
for router in (
    settings_api.router,
    datasets.router,
    configurations.router,
    experiments.router,
    evidence.router,
    library.router,
    evals.router,
    golden.router,
):
    app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "briefcase_version": briefcase.__version__,
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
    }


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend (npm run build) from this process, so one command runs
    everything. Any non-API path returns index.html and the React router takes over.
    During UI development, use `npm run dev` instead for hot reload."""
    if not (dist / "index.html").is_file():
        return
    dist = dist.resolve()
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(dist / "index.html")


mount_frontend(app, ROOT / "frontend" / "dist")
