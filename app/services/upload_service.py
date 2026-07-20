from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import UploadFile

from app.core.constants import BYTES_PER_MEBIBYTE, FILE_IO_CHUNK_BYTES


class UploadTooLargeError(ValueError):
    pass


@contextmanager
def temporary_upload(
    upload: UploadFile,
    *,
    max_bytes: int,
    suffix: str | None = None,
) -> Iterator[Path]:
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix or "", delete=False) as output:
            path = Path(output.name)
            total_bytes = 0
            while block := upload.file.read(FILE_IO_CHUNK_BYTES):
                total_bytes += len(block)
                if total_bytes > max_bytes:
                    raise UploadTooLargeError(
                        f"文件超过 {max_bytes // BYTES_PER_MEBIBYTE} 兆字节限制"
                    )
                output.write(block)
        yield path
    finally:
        upload.file.close()
        if path:
            path.unlink(missing_ok=True)
