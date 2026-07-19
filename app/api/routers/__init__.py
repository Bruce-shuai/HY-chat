from app.api.routers.admin import router as admin_router
from app.api.routers.auth import router as auth_router
from app.api.routers.chat import router as chat_router
from app.api.routers.coding_agent import router as coding_agent_router
from app.api.routers.conversations import router as conversations_router
from app.api.routers.files import router as files_router
from app.api.routers.rag import router as rag_router
from app.api.routers.system import router as system_router
from app.api.routers.traces import router as traces_router

__all__ = [
    "admin_router",
    "auth_router",
    "chat_router",
    "coding_agent_router",
    "conversations_router",
    "files_router",
    "rag_router",
    "system_router",
    "traces_router",
]
