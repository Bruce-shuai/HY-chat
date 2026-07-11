from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ImageProvider(StrEnum):
    AUTO = "auto"
    ZHIPU = "zhipu"
    OPENAI = "openai"
    MOCK = "mock"


class ImageGenerationMode(StrEnum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"


class ImageGenerationStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    MOCK = "mock"


class ImageGenerationResult(BaseModel):
    id: int
    status: ImageGenerationStatus
    mode: ImageGenerationMode
    provider: ImageProvider
    model: str
    image_url: str | None = None
    output_file_id: str | None = None
    source_file_id: str | None = None
    raw_response: dict[str, object] = Field(default_factory=dict)


class ImageGenerationSummary(BaseModel):
    id: int
    status: str
    mode: str
    provider: str
    model: str
    prompt: str
    image_url: str | None
    output_file_id: str | None
    source_file_id: str | None
    created_at: datetime
