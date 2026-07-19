from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy.orm import Session

from app.db.models import StoredFile
from app.storage.service import storage

logger = logging.getLogger(__name__)


class FileNotOwnedError(FileNotFoundError):
    pass


class FileService:
    def __init__(self, db: Session):
        self.db = db

    def create_from_path(
        self,
        *,
        path: Path,
        user_id: str,
        filename: str,
        content_type: str | None,
        conversation_id: str | None = None,
    ) -> StoredFile:
        stored = storage.put_path(path, user_id, filename, content_type)
        row = StoredFile(
            user_id=user_id,
            conversation_id=conversation_id,
            filename=filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            storage_backend=stored.storage_backend,
            object_key=stored.object_key,
            sha256=stored.sha256,
        )
        self.db.add(row)
        try:
            self.db.commit()
            self.db.refresh(row)
        except Exception:
            self.db.rollback()
            try:
                storage.delete(stored.object_key)
            except Exception:
                logger.exception(
                    "Failed to compensate orphaned storage object key=%s",
                    stored.object_key,
                )
            raise
        return row

    def get_owned(self, user_id: str, file_id: str) -> StoredFile:
        row = self.db.get(StoredFile, file_id)
        if not row or row.user_id != user_id:
            raise FileNotOwnedError("文件不存在")
        return row

    @contextmanager
    def materialize(self, row: StoredFile) -> Iterator[Path]:
        suffix = Path(row.filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            path = Path(temporary.name)
        try:
            storage.download_to(row.object_key, path)
            yield path
        finally:
            path.unlink(missing_ok=True)

    def delete(self, row: StoredFile) -> None:
        storage.delete(row.object_key)
        self.db.delete(row)
        self.db.commit()
