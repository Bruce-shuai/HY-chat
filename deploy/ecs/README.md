# ECS production deployment

This Compose stack is designed to coexist with the Nginx Proxy Manager already
installed on the target ECS host. It does not publish host ports. The frontend
and API join the external `nginx-proxy-manage_default` network.

Create two Nginx Proxy Manager proxy hosts after the stack is healthy:

- `chat.hy-ai.xyz` -> `hy-chat-frontend:3000`
- `api.chat.hy-ai.xyz` -> `hy-chat-api:8000`

Enable Websockets Support and request a Let's Encrypt certificate with Force
SSL and HTTP/2 enabled for both proxy hosts.

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

# Pull source updates and rebuild
git pull --ff-only
docker compose --env-file .env -f deploy/ecs/compose.yml up -d --build --wait

# Run database migrations manually when needed
docker compose --env-file .env -f deploy/ecs/compose.yml run --rm api \
  alembic upgrade head

# Back up PostgreSQL
docker exec hy-chat-postgres pg_dump -U hy_chat -d hy_chat_db -Fc \
  > "hy-chat-$(date +%Y%m%d-%H%M%S).dump"
```

Do not commit `/opt/hy-chat/.env`; it contains production secrets. Persistent
data lives in Docker volumes and is not removed by a normal container rebuild.
