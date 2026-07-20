from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from app.core.config import get_settings
from app.core.types import JsonObject

settings = get_settings()

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".turbo",
}
TEXT_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".env",
    ".example",
    ".css",
    ".html",
    ".sql",
    ".sh",
    ".dockerfile",
}


def safe_path(path: str | Path) -> Path:
    root = settings.workspace_path
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = root / p
    resolved = p.resolve()
    if root not in [resolved, *resolved.parents]:
        raise ValueError(f"路径不在工作区内：{resolved}")
    return resolved


def _iter_files(root: Path, max_files: int = 200) -> Iterable[Path]:
    count = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for filename in files:
            if count >= max_files:
                return
            path = Path(current) / filename
            if path.suffix.lower() in TEXT_EXTENSIONS or filename in {
                "Dockerfile",
                "Makefile",
            }:
                count += 1
                yield path


def list_files(path: str, max_files: int = 120) -> JsonObject:
    root = safe_path(path)
    if not root.exists():
        return {"files": [], "error": f"路径不存在：{root}"}
    files = [str(p.relative_to(root)) for p in _iter_files(root, max_files=max_files)]
    return {"root": str(root), "files": files, "count": len(files)}


def read_file(path: str, max_chars: int = 12000) -> JsonObject:
    p = safe_path(path)
    if not p.exists() or not p.is_file():
        return {"path": str(p), "content": "", "error": "文件不存在"}
    content = p.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    return {"path": str(p), "content": content, "truncated": len(content) >= max_chars}


def search_code(path: str, query: str, max_results: int = 40) -> JsonObject:
    root = safe_path(path)
    if not root.exists():
        return {"matches": [], "error": f"路径不存在：{root}"}

    query_lower = query.lower().strip()
    matches: list[JsonObject] = []
    if not query_lower:
        return {"matches": matches}

    for file_path in _iter_files(root, max_files=500):
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for line_no, line in enumerate(lines, start=1):
            if query_lower in line.lower():
                matches.append(
                    {
                        "file": str(file_path.relative_to(root)),
                        "line": line_no,
                        "text": line.strip()[:300],
                    }
                )
                if len(matches) >= max_results:
                    return {"query": query, "matches": matches}
    return {"query": query, "matches": matches}
