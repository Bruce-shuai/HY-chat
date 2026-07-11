from datetime import datetime

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1, description="用户自然语言任务")
    workspace: str | None = Field(
        default=None, description="要分析的项目目录，必须在 WORKSPACE_ROOT 下"
    )
    model: str | None = Field(default=None, description="可选：覆盖默认聊天模型")


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    output: str


class AgentRunSummary(BaseModel):
    id: str
    task: str
    workspace: str
    status: str
    final_output: str | None
    error_message: str | None
    created_at: datetime


class ToolCallSummary(BaseModel):
    tool_name: str
    input: dict[str, object]
    output: dict[str, object]
    status: str
    created_at: datetime


class ModelCallSummary(BaseModel):
    provider: str
    model_name: str
    status: str
    latency_ms: int | None
    created_at: datetime


class AgentRunDetail(AgentRunSummary):
    tool_calls: list[ToolCallSummary]
    model_calls: list[ModelCallSummary]
