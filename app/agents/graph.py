"""A small, separate Coding Agent workflow.

Unlike ``app.agents.chat``, this graph does not power the interactive chat UI.
It scans a mounted workspace, searches and reads a bounded set of files, then
asks the model for a plan and summary. Tool activity is persisted for the
``/coding-agent`` run-history endpoints.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langsmith import traceable
from sqlalchemy.orm import Session

from app.core.types import ChatMessagePayload, JsonObject
from app.db.models import ToolCall
from app.models.router import ModelRouter
from app.tools.file_tools import list_files, read_file, search_code


class AgentState(TypedDict, total=False):
    run_id: str
    task: str
    workspace: str
    model: str | None
    project_files: JsonObject
    search_results: JsonObject
    selected_files: list[JsonObject]
    plan: str
    final_output: str


def _save_tool_call(
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


def _extract_search_terms(task: str) -> list[str]:
    # 学习版：简单关键词提取。后续可以升级成 LLM classify / embedding search / AST symbol search。
    raw_terms = [
        token.strip(" ：:，,。.()[]{}<>`\"'")
        for token in task.replace("\n", " ").split(" ")
    ]
    terms = [t for t in raw_terms if len(t) >= 3]
    if not terms:
        terms = ["main", "app", "router", "agent", "auth", "login"]
    return terms[:5]


def build_agent_graph(db: Session):
    """Build the scan -> search -> read -> plan -> summarize workflow."""

    def scan_project_node(state: AgentState) -> AgentState:
        output = list_files(state["workspace"])
        _save_tool_call(
            db, state["run_id"], "list_files", {"path": state["workspace"]}, output
        )
        return {"project_files": output}

    def search_code_node(state: AgentState) -> AgentState:
        all_matches = []
        for term in _extract_search_terms(state["task"]):
            output = search_code(state["workspace"], term)
            _save_tool_call(
                db,
                state["run_id"],
                "search_code",
                {"path": state["workspace"], "query": term},
                output,
            )
            all_matches.extend(output.get("matches", []))
        return {"search_results": {"matches": all_matches[:60]}}

    def read_selected_files_node(state: AgentState) -> AgentState:
        files = state.get("project_files", {}).get("files", [])[:8]
        selected: list[JsonObject] = []
        for rel_file in files:
            if rel_file.endswith(
                (".py", ".ts", ".tsx", ".js", ".md", ".json", ".yml", ".yaml", ".toml")
            ):
                full_path = f"{state['workspace'].rstrip('/')}/{rel_file}"
                output = read_file(full_path, max_chars=3000)
                _save_tool_call(
                    db,
                    state["run_id"],
                    "read_file",
                    {"path": full_path},
                    {"path": output.get("path"), "truncated": output.get("truncated")},
                )
                selected.append(
                    {"file": rel_file, "content": output.get("content", "")[:3000]}
                )
            if len(selected) >= 5:
                break
        return {"selected_files": selected}

    def plan_node(state: AgentState) -> AgentState:
        router = ModelRouter(db=db, run_id=state["run_id"])
        messages: list[ChatMessagePayload] = [
            {
                "role": "system",
                "content": (
                    "你是 HY-chat，一个具备代码分析和图片生成能力的 AI 聊天助手。"
                    "你需要先基于真实文件和搜索结果生成执行计划。"
                    "不要编造没读取过的文件内容。输出中文，结构清晰。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户任务：{state['task']}\n\n"
                    f"项目文件列表：{state.get('project_files')}\n\n"
                    f"代码搜索结果：{state.get('search_results')}\n\n"
                    f"已读取文件片段：{state.get('selected_files')}\n\n"
                    "请输出：1）你对项目的判断；2）下一步执行计划；3）风险点。"
                ),
            },
        ]
        result = router.chat(messages, model=state.get("model"))
        return {"plan": result.text}

    def final_summary_node(state: AgentState) -> AgentState:
        router = ModelRouter(db=db, run_id=state["run_id"])
        messages: list[ChatMessagePayload] = [
            {
                "role": "system",
                "content": "你是一个严谨的 AI 应用工程师，负责给用户总结本次 Coding Agent 执行结果。",
            },
            {
                "role": "user",
                "content": (
                    f"用户任务：{state['task']}\n\n"
                    f"执行计划：{state.get('plan')}\n\n"
                    "请给出最终回复：说明你读到了什么、结论是什么、后续如果要改代码应该怎么做。"
                ),
            },
        ]
        result = router.chat(messages, model=state.get("model"))
        return {"final_output": result.text}

    graph = StateGraph(AgentState)
    graph.add_node("scan_project", scan_project_node)
    graph.add_node("search_code", search_code_node)
    graph.add_node("read_selected_files", read_selected_files_node)
    graph.add_node("plan", plan_node)
    graph.add_node("final_summary", final_summary_node)

    graph.add_edge(START, "scan_project")
    graph.add_edge("scan_project", "search_code")
    graph.add_edge("search_code", "read_selected_files")
    graph.add_edge("read_selected_files", "plan")
    graph.add_edge("plan", "final_summary")
    graph.add_edge("final_summary", END)

    return graph.compile()


@traceable(name="hy_chat_agent_run", run_type="chain")
def run_agent_graph(
    db: Session, run_id: str, task: str, workspace: str, model: str | None = None
) -> str:
    """Run one Coding Agent job and return its user-facing summary."""

    graph = build_agent_graph(db)
    result = graph.invoke(
        {
            "run_id": run_id,
            "task": task,
            "workspace": workspace,
            "model": model,
        },
        config={"configurable": {"thread_id": run_id}},
    )
    return result.get("final_output", "")
