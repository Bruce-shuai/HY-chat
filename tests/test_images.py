import base64
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.schemas.images import ImageGenerationMode, ImageProvider
from app.services.image_service import (
    ImageProviderCapabilityError,
    generate_image,
    settings,
)
from app.storage.service import storage


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, object] | None = None,
        *,
        content: bytes | None = None,
        content_type: str = "application/json",
    ):
        self.content = content if content is not None else json.dumps(payload).encode()
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def image_db(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "backend", "local")
    monkeypatch.setattr(storage, "local_root", tmp_path / "storage")
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_zhipu_text_to_image_request_and_storage(image_db, monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(settings, "zhipu_api_key", "test-key")

    def fake_post(url: str, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            {"created": 1, "data": [{"url": "https://image.test/a.png"}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_args, **_kwargs: FakeResponse(
            content=b"png-bytes",
            content_type="image/png",
        ),
    )

    result = generate_image(
        image_db,
        "一只猫",
        user_id="user-1",
        provider=ImageProvider.ZHIPU,
    )

    assert result.mode is ImageGenerationMode.TEXT_TO_IMAGE
    assert result.output_file_id
    assert calls[0][0].endswith("/images/generations")
    assert calls[0][1]["json"]["prompt"] == "一只猫"


def test_openai_image_to_image_uses_edit_endpoint(image_db, tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"source-image")
    captured: dict[str, object] = {}
    monkeypatch.setattr(settings, "openai_image_api_key", "test-key")

    def fake_post(url: str, **kwargs):
        captured.update({"url": url, **kwargs})
        encoded = base64.b64encode(b"edited-image").decode()
        return FakeResponse({"created": 2, "data": [{"b64_json": encoded}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = generate_image(
        image_db,
        "改成水彩风格",
        user_id="user-1",
        provider=ImageProvider.OPENAI,
        source_path=source,
        source_filename="source.png",
        source_content_type="image/png",
        source_file_id="file-1",
    )

    assert result.mode is ImageGenerationMode.IMAGE_TO_IMAGE
    assert str(captured["url"]).endswith("/images/edits")
    assert "image" in captured["files"]
    assert captured["data"]["input_fidelity"] == "high"


def test_zhipu_rejects_image_to_image(image_db, tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"source-image")
    monkeypatch.setattr(settings, "zhipu_api_key", "test-key")

    with pytest.raises(ImageProviderCapabilityError, match="不支持图生图"):
        generate_image(
            image_db,
            "修改图片",
            user_id="user-1",
            provider=ImageProvider.ZHIPU,
            source_path=source,
        )
