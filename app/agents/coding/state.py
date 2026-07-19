from __future__ import annotations

from typing import TypedDict

from app.core.types import JsonObject


class CodingAgentState(TypedDict, total=False):
    run_id: str
    task: str
    workspace: str
    model: str | None
    project_files: JsonObject
    search_results: JsonObject
    selected_files: list[JsonObject]
    plan: str
    final_output: str


SOURCE_FILE_EXTENSIONS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
)
