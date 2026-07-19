from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.services.file_service as file_service_module
from app.services.file_service import FileService


def test_file_metadata_failure_compensates_uploaded_object(tmp_path, monkeypatch):
    source = tmp_path / "document.txt"
    source.write_text("content", encoding="utf-8")
    stored = SimpleNamespace(
        object_key="users/user-1/object.txt",
        content_type="text/plain",
        size_bytes=7,
        storage_backend="local",
        sha256="a" * 64,
    )
    delete = Mock()
    monkeypatch.setattr(
        file_service_module.storage, "put_path", lambda *_args, **_kwargs: stored
    )
    monkeypatch.setattr(file_service_module.storage, "delete", delete)
    db = SimpleNamespace(
        add=Mock(),
        commit=Mock(side_effect=RuntimeError("database unavailable")),
        rollback=Mock(),
        refresh=Mock(),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        FileService(db).create_from_path(
            path=source,
            user_id="user-1",
            filename="document.txt",
            content_type="text/plain",
        )

    db.rollback.assert_called_once_with()
    delete.assert_called_once_with(stored.object_key)
