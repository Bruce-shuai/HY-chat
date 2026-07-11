from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.constants import BYTES_PER_MEBIBYTE, FILE_IO_CHUNK_BYTES
from app.db.models import User
from app.db.session import get_db
from app.rag.loaders import SUPPORTED_EXTENSIONS
from app.rag.service import RagService
from app.schemas.chat import RagSearchRequest
from app.services.file_service import FileService

router = APIRouter(prefix="/rag", tags=["rag"])
settings = get_settings()


def _serialize_document(document) -> dict[str, object]:
    return {
        "id": document.id,
        "filename": document.filename,
        "content_type": document.content_type,
        "status": document.status,
        "chunk_count": document.chunk_count,
        "metadata": document.extra_metadata,
        "error_message": document.error_message,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


@router.get("/formats")
def supported_formats():
    return {"extensions": sorted(SUPPORTED_EXTENSIONS)}


@router.post("/documents")
def upload_document(
    file: UploadFile = File(...),
    metadata: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = Path(file.filename or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{extension}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )
    try:
        parsed_metadata = json.loads(metadata) if metadata else {}
        if not isinstance(parsed_metadata, dict):
            raise ValueError("metadata must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_dir = Path(settings.rag_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"{uuid.uuid4()}-{filename}"
    stored_file = None
    try:
        total = 0
        with destination.open("wb") as output:
            while block := file.file.read(FILE_IO_CHUNK_BYTES):
                total += len(block)
                if total > settings.max_upload_bytes:
                    raise ValueError(
                        f"文件超过 {settings.max_upload_bytes // BYTES_PER_MEBIBYTE} MB 限制"
                    )
                output.write(block)
        stored_file = FileService(db).create_from_path(
            path=destination,
            user_id=user.id,
            filename=filename,
            content_type=file.content_type,
            conversation_id=None,
        )
        document = RagService(db, user_id=user.id).ingest_file(
            path=destination,
            filename=filename,
            content_type=file.content_type,
            metadata=parsed_metadata,
            stored_file_id=stored_file.id,
        )
        if document.stored_file_id != stored_file.id:
            FileService(db).delete(stored_file)
            stored_file = None
        return _serialize_document(document)
    except Exception as exc:
        if stored_file:
            try:
                FileService(db).delete(stored_file)
            except Exception:
                db.rollback()
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413 if isinstance(exc, ValueError) else 500,
            detail=str(exc),
        ) from exc
    finally:
        file.file.close()


@router.get("/documents")
def list_documents(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "documents": [
            _serialize_document(doc)
            for doc in RagService(db, user_id=user.id).list_documents()
        ]
    }


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not RagService(db, user_id=user.id).delete_document(document_id):
        raise HTTPException(status_code=404, detail="document not found")
    return {"status": "deleted", "document_id": document_id}


@router.post("/search")
def search_documents(
    request: RagSearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "query": request.query,
        "results": RagService(db, user_id=user.id).search(
            query=request.query,
            top_k=request.top_k,
            document_ids=request.document_ids,
        ),
    }
