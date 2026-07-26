from __future__ import annotations

from typing import TypedDict

from app.core.types import JsonValue


class CodingAgentState(TypedDict, total=False):
    run_id: str
    task: str
    workspace: str
    model: str | None
    project_files: dict[str, JsonValue]
    search_results: dict[str, JsonValue]
    selected_files: list[dict[str, JsonValue]]
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
