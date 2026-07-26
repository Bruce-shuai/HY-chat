from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path, PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.graph import run_agent_graph
from app.auth.dependencies import get_current_user, require_admin
from app.core.config import get_settings
from app.core.types import UserRole
from app.db.models import AgentRun, ModelCall, ToolCall, User
from app.db.session import get_db
from app.policies.service import enforce_model
from app.schemas.agent import (
    AgentRunDetail,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunSummary,
    CodingWorkspaceListResponse,
    CodingWorkspaceOption,
    ModelCallSummary,
    ToolCallSummary,
)
from app.services.redis_client import redis_client
from app.tools.file_tools import IGNORED_DIRS, TEXT_EXTENSIONS, list_files, safe_path

router = APIRouter(
    prefix="/coding-agent",
    tags=["coding-agent"],
    dependencies=[Depends(require_admin)],
)
settings = get_settings()
logger = logging.getLogger(__name__)
MAX_IMPORTED_FILES = 300
MAX_IMPORTED_BYTES = 20 * 1024 * 1024
MAX_IMPORTED_WORKSPACES = 20
MAX_IMPORTED_STORAGE_BYTES = 200 * 1024 * 1024
WORKSPACE_SCAN_FILE_LIMIT = 120
IMPORT_CHUNK_BYTES = 1024 * 1024
SPECIAL_SOURCE_FILES = {"Dockerfile", "Makefile"}


def _workspace_option(
    path: Path, source: str, *, display_name: str | None = None
) -> CodingWorkspaceOption:
    result = list_files(str(path), max_files=WORKSPACE_SCAN_FILE_LIMIT + 1)
    discovered_count = int(result.get("count", 0))
    return CodingWorkspaceOption(
        workspace_id=path.name,
        path=str(path),
        name=display_name or path.name or str(path),
        file_count=min(discovered_count, WORKSPACE_SCAN_FILE_LIMIT),
        file_count_truncated=discovered_count > WORKSPACE_SCAN_FILE_LIMIT,
        source=source,
    )


def _import_display_name(path: Path) -> str:
    return re.sub(r"-[0-9a-f]{8}$", "", path.name) or path.name


def _discover_workspaces() -> list[CodingWorkspaceOption]:
    root = settings.workspace_path
    root.mkdir(parents=True, exist_ok=True)
    options = [_workspace_option(root, "root")]
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name == "imports":
            for imported in sorted(
                child.iterdir(), key=lambda item: item.name.lower(), reverse=True
            ):
                if imported.is_dir():
                    options.append(
                        _workspace_option(
                            imported,
                            "imported",
                            display_name=_import_display_name(imported),
                        )
                    )
            continue
        options.append(_workspace_option(child, "mounted"))
    return options


def _safe_import_relative_path(filename: str) -> tuple[str, Path]:
    normalized = filename.replace("\\", "/").strip("/")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="文件夹中包含不安全的文件路径")
    root_name = parts[0] if len(parts) > 1 else "local-project"
    relative_parts = parts[1:] if len(parts) > 1 else parts
    return root_name, Path(*relative_parts)


def _is_supported_source_file(path: Path) -> bool:
    if any(part in IGNORED_DIRS for part in path.parts):
        return False
    if path.name == ".env" or (
        path.name.startswith(".env.") and path.name != ".env.example"
    ):
        return False
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in SPECIAL_SOURCE_FILES


def _import_directory_name(source_name: str) -> str:
    slug = re.sub(r"[^\w.-]+", "-", source_name, flags=re.UNICODE).strip(".-")
    return f"{slug or 'local-project'}-{uuid4().hex[:8]}"


def _import_storage_usage(imports_root: Path) -> tuple[int, int]:
    if not imports_root.exists():
        return 0, 0
    directories = [path for path in imports_root.iterdir() if path.is_dir()]
    total_bytes = sum(
        path.stat().st_size
        for directory in directories
        for path in directory.rglob("*")
        if path.is_file()
    )
    return len(directories), total_bytes


def _set_cached_run_status(status_key: str, status: str) -> None:
    """Keep Redis status best-effort; PostgreSQL remains the source of truth."""

    try:
        redis_client.setex(
            status_key,
            settings.agent_run_status_ttl_seconds,
            status,
        )
    except RedisError:
        logger.warning(
            "Coding Agent status cache unavailable key=%s status=%s",
            status_key,
            status,
            exc_info=True,
        )


@router.get("/workspaces", response_model=CodingWorkspaceListResponse)
def list_coding_workspaces() -> CodingWorkspaceListResponse:
    return CodingWorkspaceListResponse(
        root=str(settings.workspace_path),
        workspaces=_discover_workspaces(),
    )


@router.post(
    "/workspaces/import",
    response_model=CodingWorkspaceOption,
    status_code=201,
)
async def import_coding_workspace(
    files: list[UploadFile] = File(...),
) -> CodingWorkspaceOption:
    if not files:
        raise HTTPException(status_code=400, detail="请选择一个包含代码的文件夹")
    if len(files) > MAX_IMPORTED_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过多，最多可导入 {MAX_IMPORTED_FILES} 个文件",
        )

    source_name, _ = _safe_import_relative_path(files[0].filename or "")
    imports_root = safe_path(settings.workspace_path / "imports")
    workspace_count, storage_bytes = _import_storage_usage(imports_root)
    if workspace_count >= MAX_IMPORTED_WORKSPACES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"已导入项目达到 {MAX_IMPORTED_WORKSPACES} 个上限，"
                "请先删除不再使用的项目副本"
            ),
        )
    if storage_bytes >= MAX_IMPORTED_STORAGE_BYTES:
        raise HTTPException(
            status_code=409,
            detail="已导入项目占用空间达到 200 MB 上限，请先删除不再使用的项目副本",
        )

    import_root = safe_path(imports_root / _import_directory_name(source_name))
    imported_count = 0
    total_bytes = 0
    import_root.mkdir(parents=True, exist_ok=False)

    try:
        for upload in files:
            file_source_name, relative_path = _safe_import_relative_path(
                upload.filename or ""
            )
            if file_source_name != source_name:
                raise HTTPException(
                    status_code=400,
                    detail="一次只能导入一个顶层文件夹",
                )
            if not _is_supported_source_file(relative_path):
                continue
            destination = safe_path(import_root / relative_path)
            if import_root not in destination.parents:
                raise HTTPException(status_code=400, detail="文件路径超出导入目录")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as output:
                while chunk := await upload.read(IMPORT_CHUNK_BYTES):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_IMPORTED_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="文件夹过大，代码文件总大小不能超过 20 MB",
                        )
                    if storage_bytes + total_bytes > MAX_IMPORTED_STORAGE_BYTES:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                "导入后将超过 200 MB 总空间上限，"
                                "请先删除不再使用的项目副本"
                            ),
                        )
                    output.write(chunk)
            imported_count += 1
    except Exception:
        shutil.rmtree(import_root, ignore_errors=True)
        raise
    finally:
        for upload in files:
            await upload.close()

    if imported_count == 0:
        shutil.rmtree(import_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail="所选文件夹中没有支持的代码文件")
    return _workspace_option(import_root, "imported", display_name=source_name)


@router.delete("/workspaces/import/{workspace_id}", status_code=204)
def delete_coding_workspace(workspace_id: str) -> None:
    if not workspace_id or Path(workspace_id).name != workspace_id:
        raise HTTPException(status_code=400, detail="工作区标识不合法")
    import_root = safe_path(settings.workspace_path / "imports")
    target = safe_path(import_root / workspace_id)
    if target.parent != import_root or not target.is_dir():
        raise HTTPException(status_code=404, detail="导入的项目副本不存在")
    shutil.rmtree(target)


@router.post("/runs", response_model=AgentRunResponse, status_code=201)
def create_coding_agent_run(
    request: AgentRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = str(safe_path(request.workspace or settings.workspace_root))
    selected_model = request.model or settings.zhipu_chat_model
    try:
        enforce_model(db, user.id, selected_model)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    run = AgentRun(
        user_id=user.id,
        task=request.task,
        workspace=workspace,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    status_key = f"coding_agent_run:{run.id}:status"
    _set_cached_run_status(status_key, "running")

    try:
        output = run_agent_graph(
            db=db,
            run_id=run.id,
            task=request.task,
            workspace=workspace,
            model=request.model,
        )
        run.status = "success"
        run.final_output = output
        db.commit()
        _set_cached_run_status(status_key, "success")
        return AgentRunResponse(run_id=run.id, status="success", output=output)
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        db.commit()
        _set_cached_run_status(status_key, "failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/runs", response_model=list[AgentRunSummary])
def list_coding_agent_runs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AgentRunSummary]:
    statement = select(AgentRun)
    if user.role != UserRole.ADMIN:
        statement = statement.where(AgentRun.user_id == user.id)
    rows = db.scalars(
        statement.order_by(AgentRun.created_at.desc()).limit(
            settings.agent_run_list_limit
        )
    ).all()
    return [
        AgentRunSummary(
            id=row.id,
            task=row.task,
            workspace=row.workspace,
            status=row.status,
            final_output=row.final_output,
            error_message=row.error_message,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
def get_coding_agent_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunDetail:
    run = db.get(AgentRun, run_id)
    if not run or (run.user_id != user.id and user.role != UserRole.ADMIN):
        raise HTTPException(status_code=404, detail="代码智能体运行记录不存在")
    tools = db.scalars(
        select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.id.asc())
    ).all()
    models = db.scalars(
        select(ModelCall).where(ModelCall.run_id == run_id).order_by(ModelCall.id.asc())
    ).all()
    return AgentRunDetail(
        id=run.id,
        task=run.task,
        workspace=run.workspace,
        status=run.status,
        final_output=run.final_output,
        error_message=run.error_message,
        created_at=run.created_at,
        tool_calls=[
            ToolCallSummary(
                tool_name=call.tool_name,
                input=call.input,
                output=call.output,
                status=call.status,
                created_at=call.created_at,
            )
            for call in tools
        ],
        model_calls=[
            ModelCallSummary(
                provider=call.provider,
                model_name=call.model_name,
                status=call.status,
                latency_ms=call.latency_ms,
                created_at=call.created_at,
            )
            for call in models
        ],
    )
