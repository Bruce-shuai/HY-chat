from __future__ import annotations

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.db.init_db import init_db
from app.core.constants import (
    DEFAULT_STORED_IMAGE_LIST_LIMIT,
    MAX_STORED_IMAGE_LIST_LIMIT,
)
from app.db.models import StoredFile
from app.db.session import SessionLocal
from app.policies.service import runtime_user_id
from app.schemas.images import ImageProvider
from app.services.file_service import FileNotOwnedError, FileService
from app.services.image_service import generate_image as generate_image_service
from app.tools.file_tools import list_files, read_file, search_code
from app.tracing.service import safe_json


@tool
def list_workspace_files(path: str = ".") -> dict[str, object]:
    """列出工作区内指定目录的文本和代码文件。path 可以是相对工作区根目录的路径。"""

    return list_files(path)


@tool
def read_workspace_file(path: str) -> dict[str, object]:
    """读取工作区内的文本或代码文件。仅在需要了解具体内容时调用。"""

    return read_file(path)


@tool
def search_workspace_code(query: str, path: str = ".") -> dict[str, object]:
    """在工作区的代码和文本文件中搜索关键词。"""

    return search_code(path, query)


@tool
def generate_image(
    prompt: str,
    runtime: ToolRuntime,
    size: str = "1024x1024",
    source_file_id: str | None = None,
    quality: str = "auto",
) -> dict[str, object]:
    """根据提示词生成图片；提供 source_file_id 时基于该图片进行图生图编辑。"""

    try:
        init_db()
        db = SessionLocal()
        try:
            user_id = runtime_user_id(runtime)
            if not user_id:
                return {"status": "error", "error": "图片生成需要登录"}
            if source_file_id:
                try:
                    source = FileService(db).get_owned(user_id, source_file_id)
                except FileNotOwnedError:
                    return {"status": "error", "error": "来源图片不存在"}
                with FileService(db).materialize(source) as source_path:
                    result = generate_image_service(
                        db,
                        prompt,
                        user_id=user_id,
                        size=size,
                        quality=quality,
                        provider=ImageProvider.AUTO,
                        source_path=source_path,
                        source_filename=source.filename,
                        source_content_type=source.content_type,
                        source_file_id=source.id,
                    )
            else:
                result = generate_image_service(
                    db,
                    prompt,
                    user_id=user_id,
                    size=size,
                    quality=quality,
                )
            payload = safe_json(result.model_dump(mode="json"))
            if not isinstance(payload, dict):
                return {"status": "error", "error": "图片结果序列化失败"}
            return {
                **payload,
                "message": (
                    "图片已生成，请在最终回复中使用 Markdown 图片语法展示 image_url。"
                    if result.image_url
                    else "图片已生成并保存，可通过 output_file_id 在文件存储中查看。"
                ),
            }
        finally:
            db.close()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@tool
def list_stored_images(
    runtime: ToolRuntime,
    limit: int = DEFAULT_STORED_IMAGE_LIST_LIMIT,
) -> dict[str, object]:
    """列出当前用户最近上传或生成的图片，供图生图时选择 source_file_id。"""

    user_id = runtime_user_id(runtime)
    if not user_id:
        return {"status": "error", "error": "查看图片需要登录"}
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(StoredFile)
            .where(
                StoredFile.user_id == user_id,
                StoredFile.content_type.like("image/%"),
            )
            .order_by(StoredFile.created_at.desc())
            .limit(max(1, min(limit, MAX_STORED_IMAGE_LIST_LIMIT)))
        ).all()
        return {
            "images": [
                {
                    "file_id": row.id,
                    "filename": row.filename,
                    "content_type": row.content_type,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }
    finally:
        db.close()
