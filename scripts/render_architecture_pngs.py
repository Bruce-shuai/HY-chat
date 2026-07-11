from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "architecture"
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

BG = "#F7F9FC"
INK = "#172033"
MUTED = "#61708A"
LINE = "#8A99B3"
BLUE = ("#E8F1FF", "#4E7DD1")
PURPLE = ("#F0EAFE", "#8064C6")
GREEN = ("#E8F7EF", "#3D9667")
ORANGE = ("#FFF2DF", "#D38728")
RED = ("#FDEBEC", "#C95B62")
GRAY = ("#F0F3F7", "#7C8799")
CYAN = ("#E4F7F7", "#318D95")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def text_center(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    size: int = 24,
    color: str = INK,
    bold: bool = False,
    spacing: int = 8,
) -> None:
    x1, y1, x2, y2 = box
    f = font(size, bold)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(wrap(paragraph, width=max(8, int((x2 - x1) / (size * 0.95)))) or [""])
    rendered = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), rendered, font=f, spacing=spacing, align="center")
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(
        ((x1 + x2 - w) / 2, (y1 + y2 - h) / 2 - 2),
        rendered,
        font=f,
        fill=color,
        spacing=spacing,
        align="center",
    )


def section(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    color: tuple[str, str],
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=22, fill="#FFFFFF", outline="#DCE3EE", width=2)
    draw.rounded_rectangle((x1, y1, x2, y1 + 50), radius=22, fill=color[0], outline=color[1], width=2)
    draw.rectangle((x1, y1 + 28, x2, y1 + 50), fill=color[0])
    draw.text((x1 + 22, y1 + 11), title, font=font(23, True), fill=color[1])


def card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    body: str,
    color: tuple[str, str],
    title_size: int = 23,
    body_size: int = 18,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 4, y1 + 6, x2 + 4, y2 + 6), radius=18, fill="#DCE2EC")
    draw.rounded_rectangle(box, radius=18, fill=color[0], outline=color[1], width=3)
    draw.text((x1 + 18, y1 + 14), title, font=font(title_size, True), fill=color[1])
    if body:
        body_box = (x1 + 14, y1 + 47, x2 - 14, y2 - 8)
        text_center(draw, body_box, body, size=body_size, color=INK, spacing=5)


def arrow(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    label: str = "",
    color: str = LINE,
    width: int = 4,
    dashed: bool = False,
) -> None:
    if dashed:
        for a, b in zip(points, points[1:]):
            ax, ay = a
            bx, by = b
            length = max(abs(bx - ax), abs(by - ay))
            steps = max(1, length // 16)
            for i in range(0, steps, 2):
                t1, t2 = i / steps, min(1, (i + 1) / steps)
                draw.line(
                    (ax + (bx - ax) * t1, ay + (by - ay) * t1,
                     ax + (bx - ax) * t2, ay + (by - ay) * t2),
                    fill=color,
                    width=width,
                )
    else:
        draw.line(points, fill=color, width=width, joint="curve")
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    length = 15
    for delta in (2.55, -2.55):
        draw.line(
            (x2, y2, x2 + length * math.cos(angle + delta), y2 + length * math.sin(angle + delta)),
            fill=color,
            width=width,
        )
    if label:
        mid = points[len(points) // 2]
        f = font(16, True)
        bbox = draw.textbbox((0, 0), label, font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        lx, ly = mid[0] - tw / 2, mid[1] - th - 7
        draw.rounded_rectangle((lx - 6, ly - 3, lx + tw + 6, ly + th + 3), radius=7, fill=BG)
        draw.text((lx, ly), label, font=f, fill=color)


def heading(draw: ImageDraw.ImageDraw, title: str, subtitle: str, width: int) -> None:
    text_center(draw, (80, 32, width - 80, 82), title, size=38, bold=True)
    text_center(draw, (80, 86, width - 80, 120), subtitle, size=19, color=MUTED)


def render_frontend() -> Path:
    width, height = 2000, 1350
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    heading(draw, "HY-chat 前端架构", "Next.js App Router + React Providers + LangGraph SDK", width)

    section(draw, (60, 145, 1940, 360), "① 页面与路由层", BLUE)
    pages = [
        ((100, 215, 410, 325), "聊天主页 /", "Thread UI\n响应式对话工作台", BLUE),
        ((460, 215, 770, 325), "图片 /images", "生成历史、文生图\n图生图与素材选择", PURPLE),
        ((820, 215, 1130, 325), "文件 /files", "上传、查看、下载\n统一文件工作台", GREEN),
        ((1180, 215, 1490, 325), "Trace /traces", "模型与工具调用\n状态、耗时、Token", ORANGE),
        ((1540, 215, 1850, 325), "管理 /admin", "用户、角色\n配额与模型策略", RED),
    ]

    section(draw, (60, 400, 1940, 685), "② 全局状态与编排层", PURPLE)
    providers = [
        ((105, 485, 435, 625), "AuthProvider", "JWT 自动刷新\n多账号保存与切换\nauthFetch 401 重试", RED),
        ((520, 485, 850, 625), "ThreadProvider", "线程列表与检索\nURL threadId 同步\n按 assistant/graph 过滤", BLUE),
        ((935, 485, 1265, 625), "StreamProvider", "useStream 流式状态\n消息与 UI Event reducer\n新线程回写 URL", PURPLE),
        ((1350, 485, 1680, 625), "AuthBoundary", "登录态初始化\n未登录展示 LoginScreen\n保护业务页面", GREEN),
        ((1730, 485, 1895, 625), "nuqs", "URL 查询\n状态", GRAY),
    ]
    arrow(draw, [(435, 555), (520, 555)], "Token", RED[1])
    arrow(draw, [(850, 555), (935, 555)], "Thread", BLUE[1])
    arrow(draw, [(1265, 555), (1350, 555)], "状态", PURPLE[1])

    section(draw, (60, 725, 1940, 965), "③ 组件与交互层", GREEN)
    components = [
        ((105, 800, 435, 920), "Thread Components", "消息列表、输入区\n历史侧栏、Artifact", BLUE),
        ((520, 800, 850, 920), "Message Renderers", "Human / AI / Tool Calls\nMarkdown 与代码高亮", PURPLE),
        ((935, 800, 1265, 920), "Multimodal", "上传 Hook\nContent Blocks Preview\n图片与附件预览", ORANGE),
        ((1350, 800, 1680, 920), "Agent Inbox", "Interrupt 解析\n人工确认与恢复执行", RED),
        ((1730, 800, 1895, 920), "UI Kit", "Tailwind\nshadcn", GRAY),
    ]
    arrow(draw, [(1100, 625), (1100, 800)], "流式状态", PURPLE[1])
    arrow(draw, [(435, 860), (520, 860)], "组合", BLUE[1])
    arrow(draw, [(850, 860), (935, 860)], "内容块", ORANGE[1])

    section(draw, (60, 1005, 1940, 1295), "④ 浏览器状态与网络适配层", ORANGE)
    adapters = [
        ((105, 1085, 390, 1235), "localStorage", "账号列表、活动账号\nLangGraph API Key", GRAY),
        ((450, 1085, 735, 1235), "REST Client", "NEXT_PUBLIC_BACKEND_URL\nBearer Token\nFastAPI 业务接口", GREEN),
        ((795, 1085, 1080, 1235), "LangGraph SDK", "Client + useStream\nThread / Run / State", PURPLE),
        ((1140, 1085, 1425, 1235), "Next.js /api Proxy", "Edge Runtime\n透传 Authorization\n隐藏 Agent 地址", BLUE),
        ((1485, 1085, 1895, 1235), "后端入口", "FastAPI :8000\nLangGraph Agent Server :2024", RED),
    ]
    arrow(draw, [(270, 1085), (270, 625)], "恢复登录", GRAY[1])
    arrow(draw, [(600, 1085), (600, 965)], "业务请求", GREEN[1])
    arrow(draw, [(937, 1085), (1100, 965)], "流式调用", PURPLE[1])
    arrow(draw, [(1080, 1160), (1140, 1160)], "Graph API", PURPLE[1])
    arrow(draw, [(1425, 1160), (1485, 1160)], "JWT", BLUE[1])

    for args in pages + providers + components + adapters:
        card(draw, *args)

    draw.text((70, 1315), "主数据流：页面 → Provider 状态 → 组件渲染；普通业务走 FastAPI，实时 Agent 对话走 Next.js /api 代理。", font=font(17), fill=MUTED)
    output = OUT / "hy-chat-frontend-architecture.png"
    image.save(output, "PNG", optimize=True)
    return output


def render_backend() -> Path:
    width, height = 2100, 1480
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    heading(draw, "HY-chat 后端架构", "FastAPI 控制面 + LangGraph 执行面 + 统一策略、工具与数据层", width)

    section(draw, (60, 145, 2040, 345), "① 接入层", BLUE)
    ingress = [
        ((110, 215, 520, 310), "FastAPI :8000", "REST / SSE · OpenAPI · CORS · Lifespan", GREEN),
        ((650, 215, 1060, 310), "LangGraph Server :2024", "Graph / Thread / Run / Stream API", PURPLE),
        ((1190, 215, 1570, 310), "JWT Authentication", "Access / Refresh · Token Version · RBAC", RED),
        ((1700, 215, 1980, 310), "健康检查", "DB 初始化\nRedis 探活", GRAY),
    ]
    arrow(draw, [(520, 260), (1190, 260)], "Bearer", RED[1])
    arrow(draw, [(1060, 280), (1190, 280)], "自定义 Auth", RED[1])

    section(draw, (60, 385, 2040, 665), "② API 与 Agent 编排层", PURPLE)
    orchestration = [
        ((105, 470, 455, 610), "业务 Routers", "Auth · Conversations · Files\nRAG · Images · Admin · Traces", GREEN),
        ((505, 470, 855, 610), "Coding Agent Graph", "扫描 → 搜索 → 读取\n→ 计划 → 总结", ORANGE),
        ((905, 470, 1255, 610), "Chat Agent", "模型推理 ↔ Tool Calling\nThread 状态与流式输出", PURPLE),
        ((1305, 470, 1655, 610), "PolicyTraceMiddleware", "模型/工具权限 · RPM\nToken 配额 · Trace", RED),
        ((1705, 470, 1995, 610), "Model Router", "白名单 · 默认模型\n实例缓存 · 动态覆盖", BLUE),
    ]
    arrow(draw, [(280, 345), (280, 470)], "路由", GREEN[1])
    arrow(draw, [(780, 345), (1080, 470)], "运行 Graph", PURPLE[1])
    arrow(draw, [(455, 555), (505, 555)], "/coding-agent", ORANGE[1])
    arrow(draw, [(1255, 540), (1305, 540)], "每次调用", RED[1])
    arrow(draw, [(1655, 540), (1705, 540)], "选择模型", BLUE[1])

    section(draw, (60, 705, 2040, 985), "③ 能力与领域服务层", GREEN)
    capabilities = [
        ((105, 790, 405, 930), "Tool Registry", "Workspace · RAG · Web\n天气 · 股票 · 图片", ORANGE),
        ((455, 790, 755, 930), "RAG Service", "文档 Loader · Chunk\nEmbedding · 向量检索", CYAN),
        ((805, 790, 1105, 930), "Image Service", "Provider 路由\n文生图 / 图生图 / Mock", PURPLE),
        ((1155, 790, 1455, 930), "Storage Service", "Local / S3 抽象\n预签名 URL", BLUE),
        ((1505, 790, 1805, 930), "Policy Service", "用户策略 · 限流\nToken 使用统计", RED),
        ((1855, 790, 1995, 930), "Cache", "JSON\n降级", GRAY),
    ]
    arrow(draw, [(1080, 610), (1080, 705), (255, 705), (255, 790)], "调用工具", ORANGE[1])
    arrow(draw, [(405, 860), (455, 860)], "知识库", CYAN[1])
    arrow(draw, [(755, 880), (805, 880)], "Embedding", PURPLE[1])
    arrow(draw, [(1105, 860), (1155, 860)], "保存产物", BLUE[1])
    arrow(draw, [(1480, 610), (1655, 790)], "强制执行", RED[1])

    section(draw, (60, 1025, 2040, 1265), "④ 数据与基础设施层", CYAN)
    data = [
        ((105, 1100, 455, 1215), "PostgreSQL + pgvector", "用户/策略/会话/Trace\n文档分块与向量", GREEN),
        ((535, 1100, 885, 1215), "Redis", "响应/Embedding/工具缓存\nRPM 与运行状态", RED),
        ((965, 1100, 1315, 1215), "Local / S3 Storage", "上传文件、RAG 原文\n来源图与生成图片", BLUE),
        ((1395, 1100, 1745, 1215), "Shared Workspace", "Coding Agent 代码扫描\n安全路径约束", ORANGE),
        ((1825, 1100, 1995, 1215), "Volumes", "持久化\n共享", GRAY),
    ]
    arrow(draw, [(605, 930), (280, 1100)], "向量/元数据", GREEN[1])
    arrow(draw, [(1655, 930), (710, 1100)], "计数/缓存", RED[1])
    arrow(draw, [(1305, 930), (1140, 1100)], "对象", BLUE[1])
    arrow(draw, [(680, 610), (1570, 1100)], "读取代码", ORANGE[1])

    section(draw, (60, 1305, 2040, 1435), "⑤ 外部服务", ORANGE)
    external = [
        ((105, 1350, 480, 1410), "智谱 GLM", "Chat · Embedding · 文生图", PURPLE),
        ((540, 1350, 915, 1410), "OpenAI Images", "图片编辑 / 图生图", PURPLE),
        ((975, 1350, 1390, 1410), "外部数据工具", "Tavily · Open-Meteo · Alpha Vantage", ORANGE),
        ((1450, 1350, 1770, 1410), "LangSmith（可选）", "分布式 Trace", GRAY),
        ((1830, 1350, 1995, 1410), "Mock", "无 Key\n自测", CYAN),
    ]
    arrow(draw, [(1850, 610), (2030, 610), (2030, 1285), (290, 1285), (290, 1350)], "模型", PURPLE[1])
    arrow(draw, [(955, 930), (727, 1350)], "图片", PURPLE[1])
    arrow(draw, [(255, 930), (1180, 1350)], "联网工具", ORANGE[1])
    arrow(draw, [(1480, 610), (1610, 1350)], "可选 Trace", GRAY[1], dashed=True)

    for args in ingress + orchestration + capabilities + data + external:
        card(draw, *args, title_size=21, body_size=17)

    draw.text((70, 1450), "设计主线：接入分离、执行收口、策略下沉、数据共享；Redis 故障允许降级，核心权限仍由 PostgreSQL 强制执行。", font=font(17), fill=MUTED)
    output = OUT / "hy-chat-backend-architecture.png"
    image.save(output, "PNG", optimize=True)
    return output


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (render_frontend(), render_backend()):
        print(path)
