from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from app.core.admin_contact import append_admin_contact
from app.core.config import get_settings
from app.core.types import JsonObject
from app.tools.file_tools import safe_path

settings = get_settings()

ALLOWED_COMMAND_PREFIXES = [
    ["python", "-m", "pytest"],
    ["pytest"],
    ["ruff", "check"],
    ["npm", "test"],
    ["npm", "run", "test"],
]

BLOCKED_TOKENS = {
    "rm",
    "sudo",
    "curl",
    "wget",
    "ssh",
    "scp",
    "chmod",
    "chown",
    "mkfs",
    "dd",
}


def run_command(command: str, cwd: str, timeout_seconds: int = 30) -> JsonObject:
    if not settings.enable_command_tool:
        return {
            "status": "disabled",
            "message": append_admin_contact("命令执行工具未启用，请联系管理员开启。"),
        }

    args = shlex.split(command)
    if not args:
        return {"status": "error", "message": "命令不能为空"}

    if any(token in BLOCKED_TOKENS for token in args):
        return {"status": "blocked", "message": f"命令包含高风险操作：{command}"}

    allowed = any(args[: len(prefix)] == prefix for prefix in ALLOWED_COMMAND_PREFIXES)
    if not allowed:
        return {"status": "blocked", "message": f"命令不在允许范围内：{command}"}

    safe_cwd: Path = safe_path(cwd)
    proc = subprocess.run(
        args,
        cwd=str(safe_cwd),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "status": "success" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-8000:],
    }
