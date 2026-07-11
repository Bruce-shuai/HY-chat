from __future__ import annotations

from langchain_core.tools import BaseTool

from app.core.types import JsonObject
from app.tools.builtin import (
    generate_image,
    list_stored_images,
    list_workspace_files,
    read_workspace_file,
    search_workspace_code,
)
from app.tools.external import get_stock_quote, get_weather, web_search
from app.tools.rag_tools import search_knowledge_base


def get_agent_tools() -> list[BaseTool]:
    """Single extension point for tools exposed to the chat agent."""

    return [
        list_workspace_files,
        read_workspace_file,
        search_workspace_code,
        search_knowledge_base,
        web_search,
        get_weather,
        get_stock_quote,
        list_stored_images,
        generate_image,
    ]


def tool_manifest() -> list[JsonObject]:
    return [
        {"name": tool.name, "description": tool.description}
        for tool in get_agent_tools()
    ]
