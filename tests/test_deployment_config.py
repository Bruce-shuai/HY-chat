from pathlib import Path
import tomllib

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
    frontend_build_args = services["frontend"]["build"]["args"]
    api_environment = services["api"]["environment"]
    agent_environment = services["agent"]["environment"]

    assert frontend_build_args["NEXT_PUBLIC_CHAT_RUN_TIMEOUT_MS"] == (
        "${NEXT_PUBLIC_CHAT_RUN_TIMEOUT_MS:-180000}"
    )
    assert api_environment["ZHIPU_REQUEST_TIMEOUT"] == ("${ZHIPU_REQUEST_TIMEOUT:-120}")
    assert api_environment["ZHIPU_MAX_RETRIES"] == "${ZHIPU_MAX_RETRIES:-0}"
    assert agent_environment["AGENT_JOBS_PER_WORKER"] == ("${AGENT_JOBS_PER_WORKER:-2}")
    assert agent_environment["BG_JOB_TIMEOUT_SECS"] == ("${BG_JOB_TIMEOUT_SECS:-240}")
    assert agent_environment["BG_JOB_MAX_RETRIES"] == ("${BG_JOB_MAX_RETRIES:-1}")
    assert agent_environment["BG_JOB_ISOLATED_LOOPS"] == (
        "${BG_JOB_ISOLATED_LOOPS:-true}"
    )

    local_compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    local_agent = local_compose["services"]["agent"]
    assert local_agent["environment"]["AGENT_JOBS_PER_WORKER"] == (
        "${AGENT_JOBS_PER_WORKER:-2}"
    )
    assert "--n-jobs-per-worker" in local_agent["command"]


def test_agent_runtime_versions_match_across_dependency_manifests() -> None:
    expected = {
        "langgraph-api": "0.11.1",
        "langgraph-cli": "0.4.31",
        "langgraph-runtime-inmem": "0.31.1",
    }
    requirements = (ROOT / "requirements.txt").read_text().splitlines()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())

    for package, version in expected.items():
        requirement_name = (
            "langgraph-cli[inmem]" if package == "langgraph-cli" else package
        )
        exact_requirement = f"{requirement_name}=={version}"
        assert exact_requirement in requirements
        assert exact_requirement in project["project"]["dependencies"]

    locked_versions = {
        package["name"]: package["version"]
        for package in lock["package"]
        if package["name"] in expected
    }
    assert locked_versions == expected


def test_ecs_database_io_has_bounded_waits() -> None:
    compose = yaml.safe_load((ROOT / "deploy/ecs/compose.yml").read_text())
    environment = compose["services"]["api"]["environment"]

    assert environment["DATABASE_CONNECT_TIMEOUT_SECONDS"] == (
        "${DATABASE_CONNECT_TIMEOUT_SECONDS:-10}"
    )
    assert environment["DATABASE_POOL_TIMEOUT_SECONDS"] == (
        "${DATABASE_POOL_TIMEOUT_SECONDS:-10}"
    )
    assert environment["DATABASE_STATEMENT_TIMEOUT_MS"] == (
        "${DATABASE_STATEMENT_TIMEOUT_MS:-120000}"
    )
    assert environment["DATABASE_TCP_USER_TIMEOUT_MS"] == (
        "${DATABASE_TCP_USER_TIMEOUT_MS:-60000}"
    )


def test_frontend_proxy_streaming_has_bounded_unbuffered_reads() -> None:
    config = (ROOT / "deploy/ecs/nginx-proxy-manager/hy-chat-frontend.conf").read_text()

    assert "server_name hy-ai.xyz www.hy-ai.xyz chat.hy-ai.xyz;" in config
    assert "server_name hy-ai.xyz www.hy-ai.xyz;" in config
    assert "server_name chat.hy-ai.xyz;" in config
    assert config.count("location /api/ {") == 3
    assert config.count("proxy_buffering off;") >= 6
    assert config.count("proxy_cache off;") == 3
    assert config.count("proxy_read_timeout 250s;") == 3
    assert config.count("proxy_send_timeout 250s;") == 3
    assert config.count("proxy_pass http://hy-chat-agent:2024/;") == 3
    assert "proxy_pass http://hy-chat-frontend:3000;" not in config
    assert config.count("location ^~ /_next/static/ {") == 3
    assert 'Cache-Control "public, max-age=31536000, immutable"' not in config
    assert config.count("proxy_hide_header Cache-Control;") == 3
    assert (
        config.count(
            'add_header Cache-Control "private, no-store, no-cache, '
            'must-revalidate, max-age=0" always;'
        )
        == 3
    )


def test_ecs_agent_is_reachable_only_through_internal_docker_networks() -> None:
    compose = yaml.safe_load((ROOT / "deploy/ecs/compose.yml").read_text())
    agent = compose["services"]["agent"]

    assert agent["networks"] == ["default", "proxy"]
    assert "ports" not in agent
