# HY-chat

HY-chat 是一个面向多用户的 AI 聊天工作台，基于 LangChain Agent Chat UI、LangGraph、FastAPI、PostgreSQL/pgvector、Redis 和 S3 兼容对象存储构建。

![HY-chat Agent Chat UI](docs/hy-chat-ui.png)

第一次阅读或准备修改项目时，建议先看[代码阅读指南](docs/code-reading-guide.md)，其中说明了目录职责、两条 Agent 链路的区别，以及常见需求应该从哪个文件开始。

## 能力概览

- 响应式聊天界面，支持桌面、平板和手机
- 多轮对话、会话历史、新建与切换会话
- 注册、登录、JWT Access/Refresh Token、保存并切换多个账号
- 管理员与普通用户角色，以及简单的 Web 管理后台
- 每用户模型白名单、RPM、月 Token 配额和高成本工具权限
- PDF、DOCX、PPTX、XLSX、TXT、Markdown、HTML、CSV、JSON RAG
- Tavily Web Search、Open-Meteo Weather、Alpha Vantage Stock Tool Calling
- 动态模型选择、LangGraph 流式协议与 FastAPI SSE
- 模型和工具 Trace：输入、输出、耗时、Token、状态与错误
- 本地文件存储或 AWS S3、MinIO、Cloudflare R2 等 S3 兼容存储
- Redis 对话、Embedding、RAG 和外部工具缓存

## Docker Compose 启动

```bash
cp .env.example .env
```

至少修改 JWT 密钥；使用真实模型时再填写智谱 Key：

```env
JWT_SECRET_KEY=请替换为足够长的随机字符串
ZHIPU_API_KEY=
TAVILY_API_KEY=
ALPHA_VANTAGE_API_KEY=
```

默认聊天模型使用 `glm-5.2`，模型列表只保留 5 系列：`glm-5.2`、`glm-5.1`、`glm-5-turbo`。

启动全部服务：

```bash
docker compose up --build
```

访问地址：

- Web UI：<http://localhost:3000>
- FastAPI / OpenAPI：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

LangGraph Agent Server 在 Compose 网络中由 Web UI 的 `/api` 反向代理访问，不再直接暴露 `2024` 端口，避免绕过 JWT 和线程权限。本地未配置 `INITIAL_ADMIN_EMAIL` 时首个注册账号自动成为管理员；生产环境必须显式配置该邮箱，避免公开注册时被抢占管理员身份。

当前 Compose 仍使用 LangGraph 开发服务器，Checkpoint/HITL 状态通过 `agent_state` Volume 保留，适合单机演示与面试环境；它不等同于正式的 LangGraph 生产部署。

## 本地开发

先准备 PostgreSQL（带 pgvector）与 Redis，并把 `.env` 中的连接地址改成本机地址。然后启动 FastAPI：

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

另开终端启动 Agent Server：

```bash
uv run langgraph dev --host 0.0.0.0 --port 2024 --no-browser
```

再启动前端：

```bash
cd frontend
cp .env.example .env.local
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

前端浏览器访问 `/api`，Next.js 服务端通过 `LANGGRAPH_API_URL=http://localhost:2024` 转发到 Agent Server，并保留浏览器发送的 Bearer Token。

## 数据库迁移

项目使用 Alembic 管理 PostgreSQL Schema，启动 FastAPI 或 LangGraph Agent 时会自动执行 `alembic upgrade head`。手动升级可运行：

```bash
uv run alembic upgrade head
```

新增或调整 SQLAlchemy Model 后生成迁移：

```bash
uv run alembic revision --autogenerate -m "describe schema change"
```

如果在宿主机直接执行迁移，而 `.env` 里的 `DATABASE_URL` 仍使用 Compose 内部服务名 `postgres`，需要临时覆盖为 `localhost` 连接地址。

## 身份认证与账号切换

Web UI 可直接注册和登录。REST 调用先获取 Token：

```bash
curl -X POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"change-me-123","display_name":"Admin"}'
```

响应包含 `access_token`、`refresh_token` 和当前用户策略。后续请求加入：

```bash
-H 'Authorization: Bearer <access_token>'
```

相关接口：

- `POST /auth/login`
- `POST /auth/refresh`
- `GET /auth/me`
- `POST /auth/logout-all`：递增 Token 版本，使该账号已有 Token 全部失效

前端账号菜单可以保存多个已登录账号并切换。Token 存储在浏览器本地存储中，因此生产部署需要同时启用严格 CSP、HTTPS，并避免引入不可信前端脚本。

## AI 权限与后台管理

管理员访问 <http://localhost:3000/admin>，可以配置：

- 管理员或普通用户角色、账号启停
- 可调用模型列表
- 每分钟模型请求次数
- 每月 Token 配额
- 是否允许 Web Search、Stock 等高成本工具

这些策略由 Agent Server 的模型/工具中间件执行，不依赖前端按钮是否显示。Redis 用于原子 RPM 计数；模型和 Token 权限仍由数据库强制执行，Redis 暂时不可用时聊天不会整体中断。

## 会话与 Trace

左侧会话栏支持新建和切换会话。LangGraph 自定义认证会在创建线程时写入 owner，并在读取、搜索、更新、运行时按 owner 过滤。

本地 Trace 页面：<http://localhost:3000/traces>。REST 接口：

```bash
curl http://localhost:8000/traces \
  -H 'Authorization: Bearer <access_token>'

curl http://localhost:8000/traces/<trace_id> \
  -H 'Authorization: Bearer <access_token>'
```

如配置 `LANGSMITH_API_KEY` 与 `LANGSMITH_TRACING=true`，仍可同时在 LangSmith 中查看更完整的分布式 Trace。

## 人工审批（HITL）

Web 聊天默认对 `web_search` 和 `get_stock_quote` 启用人工审批。模型准备调用这些工具时，LangGraph 会暂停运行，前端允许用户批准、修改参数或拒绝，然后从同一 Thread checkpoint 继续执行。

```env
HITL_ENABLED=true
```

设置为 `false` 可关闭人工审批。HITL 仅在 LangGraph Server 链路启用；FastAPI 的 `/chat/stream` 当前没有中断恢复协议，因此会直接执行已经通过账号权限检查的工具。

## RAG 知识库

聊天输入区的“加入知识库”支持常见办公文档。所有文档和向量检索均按用户隔离。

```bash
curl -X POST http://localhost:8000/rag/documents \
  -H 'Authorization: Bearer <access_token>' \
  -F 'file=@./example.pdf'

curl -X POST http://localhost:8000/rag/search \
  -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"query":"文档的核心结论是什么？","top_k":4}'
```

配置 `ZHIPU_API_KEY` 时使用 `embedding-3`；未配置时使用确定性的本地哈希向量，便于开发测试，但检索质量较低。

## S3 与文件存储

默认使用 Docker Volume 中的本地存储：

```env
STORAGE_BACKEND=local
LOCAL_STORAGE_DIR=/data/storage
MAX_UPLOAD_BYTES=52428800
```

切换到 S3 或兼容服务：

```env
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=
S3_REGION=us-east-1
S3_BUCKET=hy-chat
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_PUBLIC_BASE_URL=
S3_PRESIGN_EXPIRY_SECONDS=900
```

`S3_ENDPOINT_URL` 留空表示 AWS S3；使用 MinIO/R2 时填写对应端点。凭据留空时 boto3 会使用其标准凭据链。下载默认返回短时预签名 URL；请保持 Bucket 私有并为运行身份配置最小权限。

文件接口支持图片和普通文件：

- `POST /files`
- `GET /files`
- `GET /files/{id}/content`
- `GET /files/{id}/download-url`
- `DELETE /files/{id}`

RAG 原始文件和用户上传附件也会进入同一存储层。

## Coding Agent

Coding Agent 路由已从含义不清的 `/agent/*` 调整为：

- `POST /coding-agent/runs`
- `GET /coding-agent/runs`
- `GET /coding-agent/runs/{id}`

## 模型、工具、SSE 与 Cache

```bash
curl http://localhost:8000/models -H 'Authorization: Bearer <access_token>'
curl http://localhost:8000/tools -H 'Authorization: Bearer <access_token>'
curl http://localhost:8000/cache/health
```

FastAPI SSE：

```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"message":"查询上海天气并总结","model":"glm-5.2"}'
```

事件类型为 `metadata`、`token`、`done` 和 `error`。缓存命中状态位于 `metadata.cache_hit`。主页面的 LangGraph 会话和 FastAPI SSE 都会使用 Redis 缓存相同用户、模型与会话上下文下的纯文本回复，命中后会跳过模型生成并立即返回；工具调用、联网、天气、股票等外部结果仍按工具自身缓存策略处理。Redis 不可用时缓存自动降级。聊天回复缓存时间可通过 `CHAT_RESPONSE_CACHE_TTL` 配置。

缓存层内置轻量防护：`CACHE_TTL_JITTER_RATIO` 为写入 TTL 增加随机抖动以降低雪崩风险，`CACHE_NEGATIVE_TTL` 为稳定空结果提供短缓存以降低穿透风险，`CACHE_LOCK_TTL` / `CACHE_LOCK_WAIT_SECONDS` / `CACHE_LOCK_POLL_SECONDS` 用 Redis lock 降低热点 key 击穿时的重复生成。

## 验证

```bash
uv run pytest -q
uv run ruff check app tests
cd frontend && corepack pnpm@10.5.1 build
```

## 架构图

- [前端架构](docs/architecture/hy-chat-frontend-architecture.png)
- [后端架构](docs/architecture/hy-chat-backend-architecture.png)
- [聊天、RAG 与 Tool Calling 流程](docs/architecture/chat-rag-tool-flow.drawio)
- [JWT、权限与配额校验流程](docs/architecture/auth-policy-flow.drawio)

前后端架构图使用 PNG 格式；专项流程图使用原生 draw.io `mxGraphModel` 格式，可继续编辑和导出 PNG、SVG 或 PDF。
