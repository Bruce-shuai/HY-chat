from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
AGENT_STATE_MOUNT = "agent_state:/app/.langgraph_api"


def test_ecs_agent_state_is_only_mounted_by_agent_service() -> None:
    compose = yaml.safe_load((ROOT / "deploy/ecs/compose.yml").read_text())
    services = compose["services"]

    assert services["api"]["environment"]["SERVICE_ROLE"] == "api"
    assert services["agent"]["environment"]["SERVICE_ROLE"] == "agent"
    assert AGENT_STATE_MOUNT not in services["api"]["volumes"]
    assert services["agent"]["volumes"].count(AGENT_STATE_MOUNT) == 1

    consumers = [
        name
        for name, service in services.items()
        if AGENT_STATE_MOUNT in service.get("volumes", [])
    ]
    assert consumers == ["agent"]
