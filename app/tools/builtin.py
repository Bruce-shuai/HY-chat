from __future__ import annotations

from langchain.tools import ToolRuntime, tool

from app.db.session import SessionLocal
from app.policies.service import (
    PolicyViolation,
    enforce_workspace_access,
    runtime_user_id,
)
from app.tools.file_tools import list_files, read_file, search_code


def _authorize_workspace_runtime(runtime: ToolRuntime) -> None:
    """Re-check access at the file tool boundary, independent of middleware."""

    user_id = runtime_user_id(runtime)
    if not user_id:
        raise PolicyViolation("工作区访问需要登录")
    db = SessionLocal()
    try:
        enforce_workspace_access(db, user_id)
    finally:
        db.close()


@tool
def list_workspace_files(runtime: ToolRuntime, path: str = ".") -> dict[str, object]:
    """列出工作区内指定目录的文本和代码文件。path 可以是相对工作区根目录的路径。"""

    _authorize_workspace_runtime(runtime)
    return list_files(path)


@tool
def read_workspace_file(path: str, runtime: ToolRuntime) -> dict[str, object]:
    """读取工作区内的文本或代码文件。仅在需要了解具体内容时调用。"""

    _authorize_workspace_runtime(runtime)
    return read_file(path)


@tool
def search_workspace_code(
    query: str, runtime: ToolRuntime, path: str = "."
) -> dict[str, object]:
    """在工作区的代码和文本文件中搜索关键词。"""

    _authorize_workspace_runtime(runtime)
    return search_code(path, query)
