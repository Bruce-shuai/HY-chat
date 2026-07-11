from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import Conversation, StoredFile, User
from app.db.session import get_db
from app.services.file_service import FileNotOwnedError, FileService
from app.services.upload_service import UploadTooLargeError, temporary_upload
from app.storage.service import storage

router = APIRouter(prefix="/files", tags=["files"])
settings = get_settings()


def serialize_file(row: StoredFile) -> dict[str, object]:
    return {
        "id": row.id,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "storage_backend": row.storage_backend,
        "conversation_id": row.conversation_id,
        "created_at": row.created_at.isoformat(),
        "download_url": f"/files/{row.id}/content",
    }


@router.post("", status_code=201)
def upload_file(
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = Path(file.filename or "file").name
    if conversation_id:
        conversation = db.get(Conversation, conversation_id)
        if not conversation or conversation.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    try:
        with temporary_upload(file, max_bytes=settings.max_upload_bytes) as temp_path:
            row = FileService(db).create_from_path(
                path=temp_path,
                user_id=user.id,
                filename=filename,
                content_type=file.content_type,
                conversation_id=conversation_id,
            )
            return serialize_file(row)
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.get("")
def list_files(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(StoredFile)
        .where(StoredFile.user_id == user.id)
        .order_by(StoredFile.created_at.desc())
    ).all()
    return {"files": [serialize_file(row) for row in rows]}


def _owned_file(db: Session, user_id: str, file_id: str) -> StoredFile:
    try:
        return FileService(db).get_owned(user_id, file_id)
    except FileNotOwnedError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc


@router.get("/{file_id}/content")
def download_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned_file(db, user.id, file_id)
    url = storage.download_url(row.object_key)
    if url:
        return RedirectResponse(url)
    path = storage.open_local(row.object_key)
    if not path.exists():
        raise HTTPException(status_code=404, detail="存储对象不存在")
    return FileResponse(path, filename=row.filename, media_type=row.content_type)


@router.get("/{file_id}/download-url")
def get_download_url(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned_file(db, user.id, file_id)
    return {
        "url": storage.download_url(row.object_key) or f"/files/{row.id}/content",
        "expires_in": settings.s3_presign_expiry_seconds,
    }


@router.delete("/{file_id}")
def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned_file(db, user.id, file_id)
    FileService(db).delete(row)
    return {"status": "deleted", "file_id": file_id}
