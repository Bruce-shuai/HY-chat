"""Compatibility entrypoint for the Coding Agent workflow.

New code should import from ``app.agents.coding``. This module remains so
existing routers, tests, and deployment references do not need to change.
"""

from __future__ import annotations

from app.agents.coding.persistence import save_tool_call as _save_tool_call
from app.agents.coding.search_terms import extract_search_terms as _extract_search_terms
from app.agents.coding.state import CodingAgentState
from app.agents.coding.workflow import build_agent_graph, run_agent_graph

AgentState = CodingAgentState

__all__ = [
    "AgentState",
    "CodingAgentState",
    "_extract_search_terms",
    "_save_tool_call",
    "build_agent_graph",
    "run_agent_graph",
]
