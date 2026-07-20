from __future__ import annotations

import logging

import httpx
from langchain.tools import tool

from app.core.admin_contact import append_admin_contact
from app.core.config import get_settings
from app.core.types import JsonObject
from app.tracing.service import safe_json

settings = get_settings()
logger = logging.getLogger(__name__)

GLM_IMAGE_PROMPT_MAX_CHARS = 1_000
RECOMMENDED_IMAGE_SIZES = {
    "1024x1024",
    "1280x1280",
    "1568x1056",
    "1056x1568",
    "1472x1088",
    "1088x1472",
    "1728x960",
    "960x1728",
}


def _images_endpoint() -> str:
    return f"{settings.zhipu_base_url.rstrip('/')}/images/generations"


def _normalize_size(size: str) -> str:
    normalized = size.strip().lower().replace("×", "x")
    return normalized or "1280x1280"


def _service_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("msg") or error.get("code")
            if message:
                return str(message)
        for key in ("message", "msg", "detail"):
            if payload.get(key):
                return str(payload[key])
    return ""


@tool
def generate_image(prompt: str, size: str = "1280x1280") -> dict[str, object]:
    """根据文字描述生成图片。用户要求画图、生成图片、做海报或视觉创意时使用。"""

    clean_prompt = " ".join(prompt.split())
    normalized_size = _normalize_size(size)

    if not settings.image_generation_enabled:
        return {
            "error": append_admin_contact(
                "图片生成暂未开启，请联系管理员开启后再试。"
            )
        }
    if not settings.zhipu_api_key:
        logger.warning("Image generation is not configured")
        return {
            "error": append_admin_contact(
                "图片生成尚未配置，请联系管理员配置图片生成服务。"
            )
        }
    if not clean_prompt:
        return {"error": "请先提供图片描述。"}
    if len(clean_prompt) > GLM_IMAGE_PROMPT_MAX_CHARS:
        return {
            "error": f"图片描述过长，请控制在 {GLM_IMAGE_PROMPT_MAX_CHARS} 个字符以内。"
        }
    if normalized_size not in RECOMMENDED_IMAGE_SIZES:
        supported = "、".join(sorted(RECOMMENDED_IMAGE_SIZES))
        return {"error": f"图片尺寸不支持，请使用这些尺寸之一：{supported}。"}

    try:
        with httpx.Client(timeout=settings.image_api_timeout) as client:
            response = client.post(
                _images_endpoint(),
                headers={
                    "Authorization": f"Bearer {settings.zhipu_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.zhipu_image_model,
                    "prompt": clean_prompt,
                    "size": normalized_size,
                    "quality": "hd",
                },
            )
            response.raise_for_status()
            payload = safe_json(response.json())
    except httpx.HTTPStatusError as exc:
        detail = _service_error_detail(exc.response)
        logger.warning(
            "Image generation failed status=%s detail=%s",
            exc.response.status_code,
            detail,
        )
        return {
            "error": (
                f"图片生成失败：{detail}" if detail else "图片生成失败，请稍后重试。"
            )
        }
    except Exception as exc:
        logger.warning("Image generation failed error=%s", type(exc).__name__)
        return {"error": "图片生成失败，请稍后重试。"}

    if not isinstance(payload, dict):
        return {"error": "图片生成服务返回异常。"}

    data = payload.get("data")
    first_item = data[0] if isinstance(data, list) and data else None
    image_url = first_item.get("url") if isinstance(first_item, dict) else None
    if not image_url:
        return {"error": "图片生成服务未返回图片链接，请稍后重试。"}

    result: JsonObject = {
        "prompt": clean_prompt,
        "image_url": str(image_url),
        "markdown": f"![生成图片]({image_url})",
        "size": normalized_size,
        "model": settings.zhipu_image_model,
        "provider": "智谱图片生成",
    }
    logger.info("Image generation completed model=%s size=%s", result["model"], size)
    return result
