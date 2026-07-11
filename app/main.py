from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    admin_router,
    auth_router,
    chat_router,
    coding_agent_router,
    conversations_router,
    files_router,
    images_router,
    rag_router,
    system_router,
    traces_router,
)
from app.cache.service import cache
from app.core.config import get_settings
from app.db.init_db import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cache.ping()
    yield


app = FastAPI(title=settings.app_name, version=settings.api_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
        "env": settings.app_env,
        "cache": {"enabled": settings.cache_enabled, "available": cache.ping()},
    }


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(coding_agent_router)
app.include_router(conversations_router)
app.include_router(files_router)
app.include_router(images_router)
app.include_router(rag_router)
app.include_router(system_router)
app.include_router(traces_router)
app.include_router(admin_router)
