"""Container entrypoint for the API and LangGraph Railway services."""

from __future__ import annotations

import os

from app.core.config import get_settings, validate_runtime_settings
from app.core.constants import AGENT_SERVER_DEFAULT_PORT, API_SERVER_DEFAULT_PORT


def _port(default: int) -> str:
    return os.getenv("PORT", str(default))


def main() -> None:
    validate_runtime_settings(get_settings())
    service_role = os.getenv("SERVICE_ROLE", "api").strip().lower()
    if service_role == "agent":
        command = [
            "langgraph",
            "dev",
            "--host",
            "0.0.0.0",
            "--port",
            _port(AGENT_SERVER_DEFAULT_PORT),
            "--no-browser",
            "--no-reload",
            "--allow-blocking",
        ]
    else:
        command = [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            _port(API_SERVER_DEFAULT_PORT),
        ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
