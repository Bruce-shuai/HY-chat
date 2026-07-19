from __future__ import annotations

DEFAULT_SEARCH_TERMS = ["main", "app", "router", "agent", "auth", "login"]
MAX_SEARCH_TERMS = 5


def extract_search_terms(task: str) -> list[str]:
    raw_terms = [
        token.strip(" ：:，,。.()[]{}<>`\"'")
        for token in task.replace("\n", " ").split(" ")
    ]
    terms = [term for term in raw_terms if len(term) >= 3]
    return (terms or DEFAULT_SEARCH_TERMS)[:MAX_SEARCH_TERMS]
