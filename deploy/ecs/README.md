# ECS production deployment

This Compose stack is designed to coexist with the Nginx Proxy Manager already
installed on the target ECS host. It does not publish host ports. The frontend
and API join the external `nginx-proxy-manage_default` network.

Create two Nginx Proxy Manager proxy hosts after the stack is healthy:

- `hy-ai.xyz` and `www.hy-ai.xyz` -> `hy-chat-frontend:3000`
- `api.hy-ai.xyz` -> `hy-chat-api:8000`

Enable Websockets Support and request a Let's Encrypt certificate with Force
SSL and HTTP/2 enabled for both proxy hosts.

## Alibaba Cloud checklist

The ECS security group must allow inbound TCP ports `80` and `443`. Port `22`
should be restricted to trusted administration addresses when possible. The
following public DNS records are required before requesting certificates:

| Record | Type | Value |
| --- | --- | --- |
| `@` | `A` | ECS public IPv4 address |
| `www` | `A` | ECS public IPv4 address |
| `api` | `A` | ECS public IPv4 address |

Verify the deployment from the server without waiting for public DNS:

```bash
curl -fsS -H 'Host: api.hy-ai.xyz' http://127.0.0.1/health
curl -fsS -H 'Host: hy-ai.xyz' http://127.0.0.1/ >/dev/null
```

The first account registered through the HY-chat UI becomes the administrator.
Register the intended owner account before inviting other users.

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

# Back up PostgreSQL
docker exec hy-chat-postgres pg_dump -U hy_chat -d hy_chat_db -Fc \
  > "hy-chat-$(date +%Y%m%d-%H%M%S).dump"
```

Do not commit `/opt/hy-chat/.env`; it contains production secrets. Persistent
data lives in Docker volumes and is not removed by a normal container rebuild.
