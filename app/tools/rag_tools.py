from __future__ import annotations

from langchain.tools import ToolRuntime, tool

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.rag.service import RagService
from app.policies.service import runtime_user_id


@tool
def search_knowledge_base(
    query: str, runtime: ToolRuntime, top_k: int = 4
) -> dict[str, object]:
    """在用户已经上传的知识库文档中进行语义检索。"""

    try:
        init_db()
        db = SessionLocal()
    except Exception as exc:
        return {"error": f"知识库暂时不可用：{exc}"}
    try:
        user_id = runtime_user_id(runtime)
        if not user_id:
            return {"error": "知识库检索需要先登录。"}
        results = RagService(db, user_id=user_id).search(query=query, top_k=top_k)
        return {
            "query": query,
            "results": results,
            "instruction": "回答时引用文件名和页码、幻灯片等来源信息，不要编造来源。",
        }
    except Exception as exc:
        return {"error": f"知识库检索失败：{exc}"}
    finally:
        db.close()
