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


def test_ecs_backend_dependencies_have_unique_mac_addresses() -> None:
    compose = yaml.safe_load((ROOT / "deploy/ecs/compose.yml").read_text())
    services = compose["services"]

    dependency_macs = {
        name: services[name]["networks"]["default"]["mac_address"]
        for name in ("postgres", "redis")
    }

    assert dependency_macs == {
        "postgres": "${POSTGRES_MAC_ADDRESS:-02:42:ff:00:00:04}",
        "redis": "${REDIS_MAC_ADDRESS:-02:42:ff:00:00:02}",
    }
    assert len(set(dependency_macs.values())) == len(dependency_macs)


def test_ecs_agent_bounds_provider_and_queue_waits() -> None:
    compose = yaml.safe_load((ROOT / "deploy/ecs/compose.yml").read_text())
    services = compose["services"]
    api_environment = services["api"]["environment"]
    agent_environment = services["agent"]["environment"]

    assert api_environment["ZHIPU_REQUEST_TIMEOUT"] == ("${ZHIPU_REQUEST_TIMEOUT:-180}")
    assert api_environment["ZHIPU_MAX_RETRIES"] == "${ZHIPU_MAX_RETRIES:-1}"
    assert agent_environment["AGENT_JOBS_PER_WORKER"] == ("${AGENT_JOBS_PER_WORKER:-2}")
    assert agent_environment["BG_JOB_TIMEOUT_SECS"] == ("${BG_JOB_TIMEOUT_SECS:-300}")
