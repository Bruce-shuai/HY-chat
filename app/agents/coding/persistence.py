from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.types import JsonObject
from app.db.models import ToolCall


def save_tool_call(
    db: Session,
    run_id: str,
    tool_name: str,
    tool_input: JsonObject,
    output: JsonObject,
    status: str = "success",
) -> None:
    row = ToolCall(
        run_id=run_id,
        tool_name=tool_name,
        input=tool_input,
        output=output,
        status=status,
    )
    db.add(row)
    db.commit()
