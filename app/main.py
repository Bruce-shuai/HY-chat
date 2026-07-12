"""FastAPI application assembly.

This module only wires infrastructure together. Business logic belongs in the
domain modules under ``app/`` (for example ``auth``, ``rag`` and ``services``),
while HTTP request handling belongs in ``app.api.routers``.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

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
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Prepare shared infrastructure when the API process starts."""

    init_db()
    cache.ping()
    yield


def _add_middleware(application: FastAPI) -> None:
    """Register cross-cutting HTTP behavior in one discoverable place."""

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def health_check():
    """Return process health without requiring authentication."""

    return {
        "status": "ok",
        "service": settings.app_name,
        "env": settings.app_env,
        "cache": {"enabled": settings.cache_enabled, "available": cache.ping()},
    }


def _add_routes(application: FastAPI) -> None:
    """Register public endpoints and feature routers."""

    application.add_api_route(
        "/health", health_check, methods=["GET"], tags=["system"]
    )
    for router in (
        auth_router,
        chat_router,
        coding_agent_router,
        conversations_router,
        files_router,
        images_router,
        rag_router,
        system_router,
        traces_router,
        admin_router,
    ):
        application.include_router(router)


def create_app() -> FastAPI:
    """Build the API application; exposed separately for tests and tooling."""

    application = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        lifespan=lifespan,
    )
    _add_middleware(application)
    _add_routes(application)
    return application


# ASGI servers import this conventional module-level object.
app = create_app()
