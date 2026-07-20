from __future__ import annotations

import hashlib
import mimetypes
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, cast

import boto3
from botocore.client import Config

from app.core.config import get_settings
from app.core.constants import BYTES_PER_MEBIBYTE, FILE_IO_CHUNK_BYTES

settings = get_settings()


class S3Client(Protocol):
    def upload_fileobj(
        self,
        file: BinaryIO,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, str] | None = None,
    ) -> None: ...

    def download_fileobj(self, bucket: str, key: str, file: BinaryIO) -> None: ...

    def generate_presigned_url(
        self,
        client_method: str,
        Params: dict[str, str],
        ExpiresIn: int,
    ) -> str: ...

    def delete_object(self, Bucket: str, Key: str) -> object: ...


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    storage_backend: str
    size_bytes: int
    sha256: str
    content_type: str


class StorageService:
    def __init__(self):
        self.backend = "s3" if settings.s3_enabled else "local"
        self.local_root = Path(settings.local_storage_dir)
        self._s3: S3Client | None = None

    @property
    def s3(self) -> S3Client:
        if self._s3 is None:
            kwargs = {
                "region_name": settings.s3_region,
                "config": Config(signature_version="s3v4"),
            }
            if settings.s3_endpoint_url:
                kwargs["endpoint_url"] = settings.s3_endpoint_url
            if settings.s3_access_key_id:
                kwargs["aws_access_key_id"] = settings.s3_access_key_id
            if settings.s3_secret_access_key:
                kwargs["aws_secret_access_key"] = settings.s3_secret_access_key
            self._s3 = cast(S3Client, boto3.client("s3", **kwargs))
        return self._s3

    @staticmethod
    def object_key(user_id: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()[:20]
        return f"users/{user_id}/{uuid.uuid4()}{suffix}"

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(FILE_IO_CHUNK_BYTES), b""):
                digest.update(block)
        return digest.hexdigest()

    def put_path(
        self,
        path: Path,
        user_id: str,
        filename: str,
        content_type: str | None = None,
    ) -> StoredObject:
        size = path.stat().st_size
        if size > settings.max_upload_bytes:
            raise ValueError(
                f"文件超过 {settings.max_upload_bytes // BYTES_PER_MEBIBYTE} 兆字节限制"
            )
        key = self.object_key(user_id, filename)
        mime = (
            content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        if self.backend == "s3":
            with path.open("rb") as source:
                self.s3.upload_fileobj(
                    source,
                    settings.s3_bucket,
                    key,
                    ExtraArgs={"ContentType": mime},
                )
        else:
            destination = self.local_root / key
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        return StoredObject(
            object_key=key,
            storage_backend=self.backend,
            size_bytes=size,
            sha256=self.sha256(path),
            content_type=mime,
        )

    def open_local(self, object_key: str) -> Path:
        path = (self.local_root / object_key).resolve()
        if self.local_root.resolve() not in path.parents:
            raise ValueError("无效的对象路径")
        return path

    def download_url(self, object_key: str) -> str | None:
        if self.backend != "s3":
            return None
        if settings.s3_public_base_url:
            return f"{settings.s3_public_base_url.rstrip('/')}/{object_key}"
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": object_key},
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )

    def download_to(self, object_key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "s3":
            with destination.open("wb") as output:
                self.s3.download_fileobj(settings.s3_bucket, object_key, output)
        else:
            shutil.copy2(self.open_local(object_key), destination)

    def delete(self, object_key: str) -> None:
        if self.backend == "s3":
            self.s3.delete_object(Bucket=settings.s3_bucket, Key=object_key)
        else:
            self.open_local(object_key).unlink(missing_ok=True)


storage = StorageService()
