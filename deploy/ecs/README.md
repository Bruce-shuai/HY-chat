# ECS production deployment

This Compose stack is designed to coexist with the Nginx Proxy Manager already
installed on the target ECS host. It does not publish host ports. The frontend
and API join the external `nginx-proxy-manage_default` network.

Create two Nginx Proxy Manager proxy hosts after the stack is healthy:

- `chat.hy-ai.xyz` -> `hy-chat-frontend:3000`
- `api.chat.hy-ai.xyz` -> `hy-chat-api:8000`

Enable Websockets Support and request a Let's Encrypt certificate with Force
SSL and HTTP/2 enabled for both proxy hosts.

The checked-in Nginx Proxy Manager snippets expect the certificate to be
available at `/etc/letsencrypt/live/hy-ai-chat/`.
They also set `client_max_body_size 72m` so the configured 50 MB attachment
limit and Base64-encoded chat attachments can reach the application. Keep this
directive when updating either proxy host.

`hy-chat-frontend.conf` mirrors the live frontend host for `hy-ai.xyz`,
`www.hy-ai.xyz`, and `chat.hy-ai.xyz`. Always validate the complete file with
`nginx -t` before reloading Nginx Proxy Manager; replacing it with a chat-only
server block would take the root and `www` domains offline.

## Run deadlines

Production uses layered deadlines so a blocked provider call cannot leave the
chat UI or every Agent worker waiting indefinitely:

- browser consultation watchdog: 180 seconds, including queue time;
- model transport request: 120 seconds with no automatic retry;
- Agent worker execution: 240 seconds with isolated worker loops;
- PostgreSQL connect/pool waits: 10 seconds, statement timeout: 120 seconds.

The browser stops its stream first, then lists only the current thread's
pending/running Runs and cancels their exact IDs. Do not replace that operation
with a global status-based cancellation.

## Alibaba Cloud checklist

The ECS security group must allow inbound TCP ports `80` and `443`. Port `22`
should be restricted to trusted administration addresses when possible. The
following public DNS records are required before requesting certificates:

| Record     | Type | Value                   |
| ---------- | ---- | ----------------------- |
| `chat`     | `A`  | ECS public IPv4 address |
| `api.chat` | `A`  | ECS public IPv4 address |

Verify the deployment from the server without waiting for public DNS:

```bash
curl -fsS -H 'Host: api.chat.hy-ai.xyz' http://127.0.0.1/health
curl -fsS -H 'Host: chat.hy-ai.xyz' http://127.0.0.1/ >/dev/null
```

Set `INITIAL_ADMIN_EMAIL` in the production `.env`. When no administrator exists,
only that email can bootstrap the administrator account; other registrations remain
ordinary users.

The current agent container still runs the LangGraph development server. Its local
checkpoint state is persisted in the `agent_state` volume to survive container
rebuilds, but this stack should still be described as a single-host demo deployment,
not a highly available LangGraph production deployment.

## Operations

Run all commands from `/opt/hy-chat` on the ECS host:

```bash
# Service status
docker compose --env-file .env -f deploy/ecs/compose.yml ps

# Recent logs
docker compose --env-file .env -f deploy/ecs/compose.yml logs --tail=200

# Pull source updates after loading the workflow-built frontend image.
git pull --ff-only
docker compose --env-file .env -f deploy/ecs/compose.yml build api
docker tag hy-chat-api:latest hy-chat-agent:latest
docker compose --env-file .env -f deploy/ecs/compose.yml \
  up -d --no-build --force-recreate api agent frontend --wait

# Run database migrations manually when needed
docker compose --env-file .env -f deploy/ecs/compose.yml run --rm api \
  alembic upgrade head

# Back up PostgreSQL
docker exec hy-chat-postgres pg_dump -U hy_chat -d hy_chat_db -Fc \
  > "hy-chat-$(date +%Y%m%d-%H%M%S).dump"
```

The ECS host is intentionally not used to compile the Next.js frontend. Run
the `Build frontend deployment image` GitHub workflow for the release commit,
download its Linux AMD64 image artifact, and load it with `docker load` before
recreating the frontend service.

For frontend-only changes with an unchanged `frontend/pnpm-lock.yaml`, create a
small architecture-neutral overlay instead of uploading the complete Node image:

```bash
./scripts/package_frontend_overlay.sh
```

The archive contains only standalone application files, static chunks, public
assets, and `Dockerfile.frontend-overlay`; it deliberately excludes
`node_modules`. Upload and extract it on ECS, then build a candidate with the
current production frontend as `BASE_IMAGE`. If the lockfile checksum differs,
use the full Linux image workflow instead—the overlay may not have newly added
Linux dependencies.

Do not commit `/opt/hy-chat/.env`; it contains production secrets. Persistent
data lives in Docker volumes and is not removed by a normal container rebuild.
