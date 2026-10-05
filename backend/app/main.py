from contextlib import asynccontextmanager

import briefcase
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import configurations, datasets, experiments
from app.api import settings as settings_api
from app.config import settings
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
for router in (settings_api.router, datasets.router, configurations.router, experiments.router):
    app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "briefcase_version": briefcase.__version__,
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
    }
