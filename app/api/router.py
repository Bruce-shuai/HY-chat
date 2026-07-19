from fastapi import APIRouter

from app.api.routers import (
    admin_router,
    auth_router,
    chat_router,
    coding_agent_router,
    conversations_router,
    files_router,
    rag_router,
    system_router,
    traces_router,
)

api_router = APIRouter()

for router in (
    auth_router,
    chat_router,
    coding_agent_router,
    conversations_router,
    files_router,
    rag_router,
    system_router,
    traces_router,
    admin_router,
):
    api_router.include_router(router)
