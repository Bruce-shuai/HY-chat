from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langsmith import traceable
from sqlalchemy.orm import Session

from app.agents.coding.nodes import CodingAgentNodes
from app.agents.coding.state import CodingAgentState


def build_agent_graph(db: Session):
    """Build the scan -> search -> read -> plan -> summarize workflow."""

    nodes = CodingAgentNodes(db)
    graph = StateGraph(CodingAgentState)
    graph.add_node("scan_project", nodes.scan_project)
    graph.add_node("search_code", nodes.search_code)
    graph.add_node("read_selected_files", nodes.read_selected_files)
    graph.add_node("plan", nodes.plan)
    graph.add_node("final_summary", nodes.final_summary)

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
