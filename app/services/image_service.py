from __future__ import annotations

import base64
import html
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from langsmith import traceable
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ImageGeneration, StoredFile
from app.schemas.images import (
    ImageGenerationMode,
    ImageGenerationResult,
    ImageGenerationStatus,
    ImageProvider,
)
from app.services.file_service import FileService
from app.storage.service import storage
from app.tracing.service import safe_json

settings = get_settings()


class ImageGenerationConfigurationError(RuntimeError):
    pass


class ImageProviderCapabilityError(ValueError):
    pass


class _ImageData(BaseModel):
    url: str | None = None
    b64_json: str | None = None


class _ImageApiResponse(BaseModel):
    created: int | None = None
    data: list[_ImageData] = Field(default_factory=list)
    usage: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class GeneratedImageAsset:
    content: bytes
    content_type: str
    extension: str
    external_url: str | None
    raw_response: dict[str, object]


class ImageGenerationService:
    def __init__(self, db: Session):
        self.db = db

    @traceable(name="image_generation", run_type="tool")
    def generate(
        self,
        *,
        prompt: str,
        user_id: str,
        size: str = "1024x1024",
        quality: str = "auto",
        provider: ImageProvider = ImageProvider.AUTO,
        model: str | None = None,
        source_path: Path | None = None,
        source_filename: str | None = None,
        source_content_type: str | None = None,
        source_file_id: str | None = None,
        mask_path: Path | None = None,
    ) -> ImageGenerationResult:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ValueError("图片提示词不能为空")
        if len(normalized_prompt) > settings.image_prompt_max_length:
            raise ValueError(
                f"图片提示词不能超过 {settings.image_prompt_max_length} 个字符"
            )

        mode = (
            ImageGenerationMode.IMAGE_TO_IMAGE
            if source_path
            else ImageGenerationMode.TEXT_TO_IMAGE
        )
        selected_provider = self._resolve_provider(provider, mode, model)
        model_name = self._resolve_model(selected_provider, model)

        try:
            if selected_provider is ImageProvider.ZHIPU:
                asset = self._generate_with_zhipu(
                    prompt=normalized_prompt,
                    size=size,
                    quality=quality,
                    model=model_name,
                )
            elif selected_provider is ImageProvider.OPENAI:
                asset = self._generate_with_openai(
                    prompt=normalized_prompt,
                    size=size,
                    quality=quality,
                    model=model_name,
                    source_path=source_path,
                    source_filename=source_filename,
                    source_content_type=source_content_type,
                    mask_path=mask_path,
                )
            else:
                asset = self._generate_mock(
                    prompt=normalized_prompt,
                    mode=mode,
                    model=model_name,
                )

            output_file = self._persist_asset(asset, user_id)
            image_url = asset.external_url or storage.download_url(
                output_file.object_key
            )
            status = (
                ImageGenerationStatus.MOCK
                if selected_provider is ImageProvider.MOCK
                else ImageGenerationStatus.SUCCESS
            )
            row = ImageGeneration(
                user_id=user_id,
                source_file_id=source_file_id,
                output_file_id=output_file.id,
                provider=selected_provider.value,
                mode=mode.value,
                quality=quality,
                prompt=normalized_prompt,
                model_name=model_name,
                image_url=image_url,
                raw_response=asset.raw_response,
                status=status.value,
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return ImageGenerationResult(
                id=row.id,
                status=status,
                mode=mode,
                provider=selected_provider,
                model=model_name,
                image_url=image_url,
                output_file_id=output_file.id,
                source_file_id=source_file_id,
                raw_response=asset.raw_response,
            )
        except Exception as exc:
            self.db.rollback()
            failed = ImageGeneration(
                user_id=user_id,
                source_file_id=source_file_id,
                provider=selected_provider.value,
                mode=mode.value,
                quality=quality,
                prompt=normalized_prompt,
                model_name=model_name,
                raw_response={"error": str(exc)},
                status=ImageGenerationStatus.FAILED.value,
            )
            self.db.add(failed)
            self.db.commit()
            raise

    @staticmethod
    def _resolve_model(provider: ImageProvider, model: str | None) -> str:
        if model:
            return model
        if provider is ImageProvider.ZHIPU:
            return settings.zhipu_image_model
        if provider is ImageProvider.OPENAI:
            return settings.openai_image_model
        return "mock-image-v1"

    @staticmethod
    def _resolve_provider(
        requested: ImageProvider,
        mode: ImageGenerationMode,
        model: str | None,
    ) -> ImageProvider:
        if (
            requested is ImageProvider.ZHIPU
            and mode is ImageGenerationMode.IMAGE_TO_IMAGE
        ):
            raise ImageProviderCapabilityError(
                "智谱当前图片生成接口不支持图生图，请选择 OpenAI provider"
            )
        if requested is ImageProvider.ZHIPU and not settings.zhipu_api_key:
            raise ImageGenerationConfigurationError("未配置 ZHIPU_API_KEY")
        if requested is ImageProvider.OPENAI and not settings.openai_image_api_key:
            raise ImageGenerationConfigurationError("未配置 OPENAI_IMAGE_API_KEY")
        if requested is not ImageProvider.AUTO:
            return requested
        if mode is ImageGenerationMode.IMAGE_TO_IMAGE:
            return (
                ImageProvider.OPENAI
                if settings.openai_image_api_key
                else ImageProvider.MOCK
            )
        if model and model.startswith("gpt-image"):
            return (
                ImageProvider.OPENAI
                if settings.openai_image_api_key
                else ImageProvider.MOCK
            )
        if settings.zhipu_api_key:
            return ImageProvider.ZHIPU
        if settings.openai_image_api_key:
            return ImageProvider.OPENAI
        return ImageProvider.MOCK

    def _generate_with_zhipu(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
        model: str,
    ) -> GeneratedImageAsset:
        payload: dict[str, object] = {
            "model": model,
            "prompt": prompt,
            "size": size,
        }
        if quality != "auto":
            payload["quality"] = quality
        response = httpx.post(
            f"{settings.zhipu_base_url.rstrip('/')}/images/generations",
            json=payload,
            headers={"Authorization": f"Bearer {settings.zhipu_api_key}"},
            timeout=settings.image_api_timeout_seconds,
        )
        response.raise_for_status()
        parsed = _ImageApiResponse.model_validate_json(response.content)
        if not parsed.data or not parsed.data[0].url:
            raise RuntimeError("智谱图片接口未返回图片 URL")
        external_url = parsed.data[0].url
        content, content_type = self._download_image(external_url)
        return GeneratedImageAsset(
            content=content,
            content_type=content_type,
            extension=self._extension_for(content_type),
            external_url=external_url,
            raw_response={
                "created": parsed.created,
                "provider": ImageProvider.ZHIPU.value,
            },
        )

    def _generate_with_openai(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
        model: str,
        source_path: Path | None,
        source_filename: str | None,
        source_content_type: str | None,
        mask_path: Path | None,
    ) -> GeneratedImageAsset:
        headers = {"Authorization": f"Bearer {settings.openai_image_api_key}"}
        endpoint = "edits" if source_path else "generations"
        url = f"{settings.openai_image_base_url.rstrip('/')}/images/{endpoint}"
        if source_path:
            filename = source_filename or source_path.name
            content_type = source_content_type or "image/png"
            files: dict[str, tuple[str, bytes, str]] = {
                "image": (filename, source_path.read_bytes(), content_type)
            }
            if mask_path:
                files["mask"] = (mask_path.name, mask_path.read_bytes(), "image/png")
            response = httpx.post(
                url,
                data={
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "input_fidelity": "high",
                },
                files=files,
                headers=headers,
                timeout=settings.image_api_timeout_seconds,
            )
        else:
            response = httpx.post(
                url,
                json={
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "output_format": "png",
                },
                headers=headers,
                timeout=settings.image_api_timeout_seconds,
            )
        response.raise_for_status()
        parsed = _ImageApiResponse.model_validate_json(response.content)
        if not parsed.data:
            raise RuntimeError("OpenAI 图片接口未返回图片")
        first = parsed.data[0]
        if first.b64_json:
            content = base64.b64decode(first.b64_json, validate=True)
            external_url = None
            content_type = "image/png"
        elif first.url:
            content, content_type = self._download_image(first.url)
            external_url = first.url
        else:
            raise RuntimeError("OpenAI 图片接口响应中缺少 b64_json 或 URL")
        return GeneratedImageAsset(
            content=content,
            content_type=content_type,
            extension=self._extension_for(content_type),
            external_url=external_url,
            raw_response={
                "created": parsed.created,
                "usage": safe_json(parsed.usage),
                "provider": ImageProvider.OPENAI.value,
            },
        )

    @staticmethod
    def _generate_mock(
        *,
        prompt: str,
        mode: ImageGenerationMode,
        model: str,
    ) -> GeneratedImageAsset:
        escaped_prompt = html.escape(prompt[:160])
        label = (
            "图生图 Mock"
            if mode is ImageGenerationMode.IMAGE_TO_IMAGE
            else "文生图 Mock"
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#0f172a"/><stop offset="1" stop-color="#334155"/></linearGradient></defs>
<rect width="1024" height="1024" rx="64" fill="url(#g)"/><text x="80" y="150" fill="white" font-size="58" font-family="sans-serif" font-weight="700">HY-chat · {label}</text><text x="80" y="250" fill="#cbd5e1" font-size="30" font-family="sans-serif">{escaped_prompt}</text><text x="80" y="920" fill="#94a3b8" font-size="24" font-family="sans-serif">配置图片 Provider API Key 后启用真实模型</text></svg>"""
        return GeneratedImageAsset(
            content=svg.encode("utf-8"),
            content_type="image/svg+xml",
            extension=".svg",
            external_url=None,
            raw_response={
                "mock": True,
                "provider": ImageProvider.MOCK.value,
                "mode": mode.value,
                "model": model,
            },
        )

    def _persist_asset(
        self,
        asset: GeneratedImageAsset,
        user_id: str,
    ) -> StoredFile:
        with tempfile.NamedTemporaryFile(
            suffix=asset.extension, delete=False
        ) as output:
            path = Path(output.name)
            output.write(asset.content)
        try:
            return FileService(self.db).create_from_path(
                path=path,
                user_id=user_id,
                filename=f"generated-{uuid.uuid4()}{asset.extension}",
                content_type=asset.content_type,
            )
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _extension_for(content_type: str) -> str:
        return {
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
        }.get(content_type, ".png")

    @staticmethod
    def _download_image(url: str) -> tuple[bytes, str]:
        response = httpx.get(
            url,
            timeout=settings.image_download_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/png").split(";")[0]
        return response.content, content_type


def generate_image(
    db: Session,
    prompt: str,
    *,
    user_id: str,
    size: str = "1024x1024",
    quality: str = "auto",
    provider: ImageProvider = ImageProvider.AUTO,
    model: str | None = None,
    source_path: Path | None = None,
    source_filename: str | None = None,
    source_content_type: str | None = None,
    source_file_id: str | None = None,
    mask_path: Path | None = None,
) -> ImageGenerationResult:
    return ImageGenerationService(db).generate(
        prompt=prompt,
        user_id=user_id,
        size=size,
        quality=quality,
        provider=provider,
        model=model,
        source_path=source_path,
        source_filename=source_filename,
        source_content_type=source_content_type,
        source_file_id=source_file_id,
        mask_path=mask_path,
    )
