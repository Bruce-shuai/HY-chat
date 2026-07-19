from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.coding.persistence import save_tool_call
from app.agents.coding.search_terms import extract_search_terms
from app.agents.coding.state import CodingAgentState, SOURCE_FILE_EXTENSIONS
from app.core.types import ChatMessagePayload, ChatRole, JsonObject
from app.models.router import ModelRouter
from app.tools.file_tools import list_files, read_file, search_code

MAX_SEARCH_RESULTS = 60
MAX_PROJECT_FILES_TO_CONSIDER = 8
MAX_SELECTED_FILES = 5
FILE_READ_LIMIT_CHARS = 3_000


class CodingAgentNodes:
    def __init__(self, db: Session):
        self.db = db

    def scan_project(self, state: CodingAgentState) -> CodingAgentState:
        output = list_files(state["workspace"])
        save_tool_call(
            self.db, state["run_id"], "list_files", {"path": state["workspace"]}, output
        )
        return {"project_files": output}

    def search_code(self, state: CodingAgentState) -> CodingAgentState:
        all_matches: list[JsonObject] = []
        for term in extract_search_terms(state["task"]):
            output = search_code(state["workspace"], term)
            save_tool_call(
                self.db,
                state["run_id"],
                "search_code",
                {"path": state["workspace"], "query": term},
                output,
            )
            all_matches.extend(output.get("matches", []))
        return {"search_results": {"matches": all_matches[:MAX_SEARCH_RESULTS]}}

    def read_selected_files(self, state: CodingAgentState) -> CodingAgentState:
        files = state.get("project_files", {}).get("files", [])[
            :MAX_PROJECT_FILES_TO_CONSIDER
        ]
        selected: list[JsonObject] = []

        for rel_file in files:
            if rel_file.endswith(SOURCE_FILE_EXTENSIONS):
                full_path = f"{state['workspace'].rstrip('/')}/{rel_file}"
                output = read_file(full_path, max_chars=FILE_READ_LIMIT_CHARS)
                save_tool_call(
                    self.db,
                    state["run_id"],
                    "read_file",
                    {"path": full_path},
                    {"path": output.get("path"), "truncated": output.get("truncated")},
                )
                selected.append(
                    {
                        "file": rel_file,
                        "content": output.get("content", "")[:FILE_READ_LIMIT_CHARS],
                    }
                )

            if len(selected) >= MAX_SELECTED_FILES:
                break

        return {"selected_files": selected}

    def plan(self, state: CodingAgentState) -> CodingAgentState:
        router = ModelRouter(db=self.db, run_id=state["run_id"])
        messages: list[ChatMessagePayload] = [
            {
                "role": ChatRole.SYSTEM,
                "content": (
                    "你是 HY-chat，一个具备代码分析能力的 AI 聊天助手。"
                    "你需要先基于真实文件和搜索结果生成执行计划。"
                    "不要编造没读取过的文件内容。输出中文，结构清晰。"
                ),
            },
            {
                "role": ChatRole.USER,
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

    def final_summary(self, state: CodingAgentState) -> CodingAgentState:
        router = ModelRouter(db=self.db, run_id=state["run_id"])
        messages: list[ChatMessagePayload] = [
            {
                "role": ChatRole.SYSTEM,
                "content": (
                    "你是一个严谨的 AI 应用工程师，负责给用户总结本次 "
                    "Coding Agent 执行结果。"
                ),
            },
            {
                "role": ChatRole.USER,
                "content": (
                    f"用户任务：{state['task']}\n\n"
                    f"执行计划：{state.get('plan')}\n\n"
                    "请给出最终回复：说明你读到了什么、结论是什么、后续如果要改代码应该怎么做。"
                ),
            },
        ]
        result = router.chat(messages, model=state.get("model"))
        return {"final_output": result.text}
