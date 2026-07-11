# ECS production deployment

This Compose stack is designed to coexist with the Nginx Proxy Manager already
installed on the target ECS host. It does not publish host ports. The frontend
and API join the external `nginx-proxy-manage_default` network.

Create two Nginx Proxy Manager proxy hosts after the stack is healthy:

- `hy-ai.xyz` and `www.hy-ai.xyz` -> `hy-chat-frontend:3000`
- `api.hy-ai.xyz` -> `hy-chat-api:8000`

Enable Websockets Support and request a Let's Encrypt certificate with Force
SSL and HTTP/2 enabled for both proxy hosts.
