from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.constants import SUPPORTED_IMAGE_CONTENT_TYPES, SUPPORTED_IMAGE_EXTENSIONS
from app.db.models import ImageGeneration, User
from app.db.session import get_db
from app.policies.service import enforce_tool
from app.schemas.images import (
    ImageGenerationResult,
    ImageGenerationSummary,
    ImageProvider,
)
from app.services.file_service import FileNotOwnedError, FileService
from app.services.image_service import (
    ImageGenerationConfigurationError,
    ImageProviderCapabilityError,
    generate_image,
)
from app.services.upload_service import UploadTooLargeError, temporary_upload

router = APIRouter(prefix="/images", tags=["images"])
settings = get_settings()


def _validate_source_image(upload: UploadFile) -> None:
    filename = Path(upload.filename or "image").name
    extension = Path(filename).suffix.lower()
    if upload.content_type not in SUPPORTED_IMAGE_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="图生图仅支持 JPG、PNG 和 WebP")
    if extension not in SUPPORTED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="图片扩展名必须是 JPG、PNG 或 WebP")


def _summary(row: ImageGeneration) -> ImageGenerationSummary:
    return ImageGenerationSummary(
        id=row.id,
        status=row.status,
        mode=row.mode,
        provider=row.provider,
        model=row.model_name,
        prompt=row.prompt,
        image_url=row.image_url,
        output_file_id=row.output_file_id,
        source_file_id=row.source_file_id,
        created_at=row.created_at,
    )


@router.get("/capabilities")
def image_capabilities(user: User = Depends(get_current_user)):
    return {
        "enabled": user.policy.allow_image_generation,
        "providers": {
            "zhipu": {
                "configured": bool(settings.zhipu_api_key),
                "text_to_image": True,
                "image_to_image": False,
                "model": settings.zhipu_image_model,
            },
            "openai": {
                "configured": bool(settings.openai_image_api_key),
                "text_to_image": True,
                "image_to_image": True,
                "model": settings.openai_image_model,
            },
            "mock": {
                "configured": True,
                "text_to_image": True,
                "image_to_image": True,
                "model": "mock-image-v1",
            },
        },
        "source_formats": sorted(SUPPORTED_IMAGE_EXTENSIONS),
        "max_source_bytes": settings.image_input_max_bytes,
    }


@router.post("/generations", response_model=ImageGenerationResult, status_code=201)
def create_image_generation(
    prompt: str = Form(..., min_length=1),
    source_image: UploadFile | None = File(default=None),
    source_file_id: str | None = Form(default=None),
    mask: UploadFile | None = File(default=None),
    provider: ImageProvider = Form(default=ImageProvider.AUTO),
    model: str | None = Form(default=None),
    size: str = Form(default="1024x1024"),
    quality: str = Form(default="auto"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        enforce_tool(db, user.id, "generate_image")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if source_image and source_file_id:
        raise HTTPException(
            status_code=400,
            detail="source_image 与 source_file_id 只能提供一个",
        )
    if mask and not (source_image or source_file_id):
        raise HTTPException(status_code=400, detail="使用 mask 时必须提供来源图片")
    if (source_image or source_file_id) and provider is ImageProvider.ZHIPU:
        raise HTTPException(
            status_code=400,
            detail="智谱当前图片生成接口不支持图生图，请选择 OpenAI provider",
        )
    if provider is ImageProvider.OPENAI and not settings.openai_image_api_key:
        raise HTTPException(status_code=503, detail="未配置 OPENAI_IMAGE_API_KEY")
    if provider is ImageProvider.ZHIPU and not settings.zhipu_api_key:
        raise HTTPException(status_code=503, detail="未配置 ZHIPU_API_KEY")

    file_service = FileService(db)
    try:
        with ExitStack() as stack:
            source_path: Path | None = None
            source_filename: str | None = None
            source_content_type: str | None = None
            resolved_source_id = source_file_id

            if source_image:
                _validate_source_image(source_image)
                source_filename = Path(source_image.filename or "source.png").name
                source_content_type = source_image.content_type
                source_path = stack.enter_context(
                    temporary_upload(
                        source_image,
                        max_bytes=settings.image_input_max_bytes,
                        suffix=Path(source_filename).suffix,
                    )
                )
                source_row = file_service.create_from_path(
                    path=source_path,
                    user_id=user.id,
                    filename=source_filename,
                    content_type=source_content_type,
                )
                resolved_source_id = source_row.id
            elif source_file_id:
                try:
                    source_row = file_service.get_owned(user.id, source_file_id)
                except FileNotOwnedError as exc:
                    raise HTTPException(
                        status_code=404, detail="来源图片不存在"
                    ) from exc
                if source_row.content_type not in SUPPORTED_IMAGE_CONTENT_TYPES:
                    raise HTTPException(
                        status_code=415,
                        detail="来源文件必须是 JPG、PNG 或 WebP 图片",
                    )
                source_filename = source_row.filename
                source_content_type = source_row.content_type
                source_path = stack.enter_context(file_service.materialize(source_row))

            mask_path: Path | None = None
            if mask:
                if mask.content_type != "image/png":
                    raise HTTPException(status_code=415, detail="mask 必须是 PNG 图片")
                mask_path = stack.enter_context(
                    temporary_upload(
                        mask,
                        max_bytes=settings.image_input_max_bytes,
                        suffix=".png",
                    )
                )

            return generate_image(
                db,
                prompt,
                user_id=user.id,
                size=size,
                quality=quality,
                provider=provider,
                model=model,
                source_path=source_path,
                source_filename=source_filename,
                source_content_type=source_content_type,
                source_file_id=resolved_source_id,
                mask_path=mask_path,
            )
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except HTTPException:
        raise
    except ImageGenerationConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ImageProviderCapabilityError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/generations")
def list_image_generations(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(ImageGeneration)
        .where(ImageGeneration.user_id == user.id)
        .order_by(ImageGeneration.created_at.desc())
        .limit(limit)
    ).all()
    return {"generations": [_summary(row) for row in rows]}


@router.get("/generations/{generation_id}", response_model=ImageGenerationSummary)
def get_image_generation(
    generation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(ImageGeneration, generation_id)
    if not row or (row.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="图片生成记录不存在")
    return _summary(row)
