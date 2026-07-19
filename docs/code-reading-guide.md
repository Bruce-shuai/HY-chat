# HY-chat 代码阅读指南

这份文档回答三个问题：项目分成哪些部分、一次请求如何流转、修改某个功能应该从哪里开始。

## 1. 先建立整体印象

```text
HY-chat/
├── app/                    # Python 后端
│   ├── api/routers/        # FastAPI HTTP 接口：解析请求、调用领域服务
│   ├── agents/             # LangGraph 对话图；coding/ 存放 Coding Agent 工作流
│   ├── auth/               # JWT、密码、当前用户和 LangGraph 鉴权
│   ├── policies/           # 模型、工具、RPM 与 Token 配额校验
│   ├── models/             # 可用模型目录及模型客户端选择
│   ├── tools/              # Agent 可调用的工具及注册表
│   ├── rag/                # 文档解析、向量化与检索
│   ├── services/           # 文件、上传和 Redis 领域服务
│   ├── storage/            # 本地/S3 对象存储适配层
│   ├── db/                 # SQLAlchemy 会话、表模型和迁移入口
│   ├── schemas/            # API 输入输出的数据结构
│   ├── tracing/            # Trace 数据清洗与记录辅助函数
│   ├── core/               # 配置、常量和共享类型
│   ├── main.py             # FastAPI 应用装配入口
│   └── entrypoint.py       # 容器中选择 API 或 Agent Server 进程
├── migrations/             # Alembic 数据库迁移脚本
├── frontend/src/
│   ├── app/                # Next.js 页面与 LangGraph 反向代理
│   ├── components/         # 通用 UI 和聊天主界面组件
│   ├── features/           # 按业务能力组织的前端模块，例如 threads/
│   ├── providers/          # 登录、会话和流式响应的共享状态
│   ├── hooks/              # 文件上传等可复用交互逻辑
│   └── lib/                # API Key、多模态消息等纯辅助函数
├── tests/                  # 后端接口与核心服务测试
├── docs/architecture/      # 可编辑的 draw.io 架构图
└── deploy/                 # ECS 等部署配置与运维脚本
```

依赖方向尽量保持为：`router -> service/domain -> db/storage/external API`。Router 负责 HTTP 细节，不应承载大段业务逻辑；`core` 也不应反向依赖具体功能。

## 2. 两条 Agent 链路不要混淆

项目里有两套用途不同的图：

- `app/agents/chat.py` 是聊天 UI 使用的主 Agent。它支持动态模型、Tool Calling、权限校验和 Trace；未配置模型 Key 时会切换到 Mock 图。
- `app/agents/coding/` 是 `/coding-agent/*` 接口使用的代码分析工作流。它按“扫描文件、搜索、读取、制定计划、总结”的固定顺序运行；`app/agents/graph.py` 只保留兼容导出。

看到 `graph` 时先确认调用方属于哪条链路，能避免在错误的入口排查。

## 3. 一次聊天请求如何流转

1. `frontend/src/app/page.tsx` 装配认证、会话、流式响应和聊天界面 Provider。
2. `frontend/src/providers/Stream.tsx` 使用 LangGraph SDK 发起流式请求。
3. `frontend/src/app/api/[..._path]/route.ts` 把请求代理给 LangGraph Agent Server，并保留 Bearer Token。
4. `app/auth/langgraph.py` 校验身份和线程归属。
5. `app/agents/chat.py` 选择模型；`PolicyTraceMiddleware` 在每次模型或工具调用前检查权限，并在调用后记录 Trace 与 Token。
6. Agent 按需从 `app/tools/registry.py` 取得工具，再进入 RAG、文件或外部 API 模块。

FastAPI 的 `/chat/stream` 是另一条可直接调用的 SSE 入口，代码在 `app/api/routers/chat.py`。排查问题时先确认客户端使用 LangGraph SDK 还是 FastAPI SSE。

## 4. 常见修改从哪里开始

| 需求               | 首先查看                          | 通常还会涉及                              |
| ------------------ | --------------------------------- | ----------------------------------------- |
| 增加 REST 接口     | `app/api/routers/`                | `schemas/`、对应 service、`app/main.py`   |
| 增加 Agent 工具    | `app/tools/registry.py`           | `app/tools/`、`policies/service.py`       |
| 调整模型列表或路由 | `app/models/catalog.py`           | `core/config.py`、管理后台                |
| 调整登录和权限     | `app/auth/`                       | `policies/`、`db/models.py`               |
| 调整数据库结构     | `app/db/models.py`                | `migrations/versions/`                    |
| 修改 RAG           | `app/rag/service.py`              | `loaders.py`、`embeddings.py`、RAG router |
| 修改文件存储       | `app/services/`                   | `app/storage/service.py`、对应 router     |
| 修改聊天界面       | `frontend/src/components/thread/` | `providers/Stream.tsx`                    |
| 修改会话侧边栏     | `frontend/src/features/threads/`  | `providers/Thread.tsx`                    |
| 修改账号状态       | `frontend/src/providers/Auth.tsx` | `components/auth/`                        |

## 5. 推荐阅读顺序

如果想快速理解主流程，可以按下面的顺序阅读：

1. `app/main.py`：后端由哪些路由组成。
2. `app/core/config.py`：系统有哪些外部依赖和功能开关。
3. `app/agents/chat.py`：主聊天图、策略和 Trace 的关系。
4. `app/tools/registry.py`：模型实际能调用哪些能力。
5. `app/db/models.py` 和 `migrations/versions/`：核心数据如何落库与演进。
6. `frontend/src/app/page.tsx` 和 `frontend/src/providers/Stream.tsx`：前端如何连接 Agent。

阅读具体功能时，再从 router 顺着调用跳到 service 和数据层；这样比逐目录通读更容易建立因果关系。

## 6. 注释约定

- 模块注释说明“这个文件负责什么、与相似模块有什么区别”。
- 函数名已能表达的步骤不重复注释；注释重点解释权限、降级、兼容性等不直观原因。
- API 输入输出优先用 Pydantic 类型表达，不用注释补偿模糊类型。
- 临时方案写清适用边界和后续方向，例如 Coding Agent 当前的简单关键词提取。

修改后可用以下命令验证：

```bash
uv run ruff check app tests
uv run pytest -q
uv run alembic upgrade head
cd frontend && corepack pnpm@10.5.1 build
```
