from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ModelCall
from app.models.catalog import get_chat_model, resolve_model
from app.core.config import get_settings
from app.core.types import ChatMessagePayload

settings = get_settings()


@dataclass
class ModelResult:
    text: str
    latency_ms: int
    model_name: str
    provider: str = "zhipu"


class ModelRouter:
    """模型路由层。

    当前默认接智谱 OpenAI-compatible API。
    没有配置 ZHIPU_API_KEY 时，返回 mock 输出，保证项目能先跑起来。
    """

    def __init__(self, db: Session | None = None, run_id: str | None = None):
        self.db = db
        self.run_id = run_id

    def chat(
        self,
        messages: list[ChatMessagePayload],
        model: str | None = None,
    ) -> ModelResult:
        model_name = resolve_model(model)
        started = time.perf_counter()

        if not settings.zhipu_api_key:
            text = self._mock_response(messages)
            latency_ms = int((time.perf_counter() - started) * 1000)
            result = ModelResult(
                text=text, latency_ms=latency_ms, model_name=model_name
            )
            self._save_model_call(messages, result, status="mock")
            return result

        llm = get_chat_model(model_name, streaming=False)
        response = llm.invoke(messages)
        text = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = ModelResult(text=text, latency_ms=latency_ms, model_name=model_name)
        self._save_model_call(messages, result)
        return result

    def _mock_response(self, messages: list[ChatMessagePayload]) -> str:
        last = messages[-1].get("content", "") if messages else ""
        return (
            "【Mock 模型输出】\n"
            "你还没有配置 ZHIPU_API_KEY，所以这里没有真实调用大模型。\n\n"
            "我已经接收到了任务，并基于项目扫描结果生成了一个学习版回复。\n\n"
            f"用户任务片段：{last[:500]}"
        )

    def _save_model_call(
        self,
        messages: list[ChatMessagePayload],
        result: ModelResult,
        status: str = "success",
    ) -> None:
        if not self.db or not self.run_id:
            return
        row = ModelCall(
            run_id=self.run_id,
            provider=result.provider,
            model_name=result.model_name,
            input={"messages": messages},
            output={"text": result.text},
            status=status,
            latency_ms=result.latency_ms,
        )
        self.db.add(row)
        self.db.commit()
