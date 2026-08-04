# 图像理解 MCP 服务器 — 实施方案

## 1. 项目定位

为不支持图像理解的文本模型（如 DeepSeek、Qwen 纯文本版、本地 LLM 等）提供"视觉外包"能力：
客户端把图片 + prompt 通过 MCP 协议发给本服务器，服务器转发给后端视觉模型，返回描述文本给客户端。

本服务器是**协议适配与转发层**，自身不做视觉推理。

### 参考项目（取其精华）

| 参考项目 | 借鉴点 |
|---|---|
| `luma-mcp` | 双层 prompt 注入（`BASE_VISION_PROMPT` + per-call `prompt`）、`task_type` 路由、自定义端点的鉴权头模板 `{{key}}`、截图大图多裁剪 |
| `vllm-mcp` | Docker + docker-compose、stdio/HTTP/SSE 多传输、provider 模块化、`config.json` 结构 |
| `VisionPower` | 配置优先级（env > config > 默认）、SSRF/路径白名单/magic byte 校验、指数退避重试 |
| `vision-tool` | 多后端并行 + 首成功取消（作为可选策略，本期默认不启用） |

## 2. 技术选型

| 维度 | 选型 | 理由 |
|---|---|---|
| 语言 | **Python 3.11+** | 用户首选；MCP 官方 SDK 一等支持；视觉模型生态多为 Python |
| MCP SDK | `mcp` v2（`MCPServer` / Streamable HTTP） | 官方最新；Streamable HTTP 是 2026-07-28 规范推荐传输 |
| HTTP 框架 | SDK 内置（基于 Starlette/Uvicorn） | 不额外引入框架，SDK 的 `run(transport=...)` 直接起服务 |
| HTTP 客户端 | `httpx`（async） | 异步、流式、超时控制好 |
| 配置 | `pydantic-settings`（env + TOML/JSON 双源） | 类型安全、与 SDK 风格一致 |
| Web 后台 | **轻量内置**（FastAPI + Jinja2 模板，单页） | 非强需求，但提供最小后台用于在线改配置 + 测试图片；可裁剪 |
| 容器 | Docker + docker-compose | 强需求 |
| 包管理 | `uv` | 快、与 SDK 文档一致 |

### 传输协议

- **默认：Streamable HTTP**（`/mcp` 端点），适配远程客户端通过 HTTP 调用
- **可选：stdio**，用于 Claude Desktop / Cursor 等本地客户端直接挂载
- **SSE：保留兼容但非默认**（SDK 仍支持，老客户端可用）
- 由 `MCP_TRANSPORT` 环境变量切换

## 3. 目录结构

```
depu_img_mcp_sever/
├── src/depu_img_mcp/
│   ├── __init__.py
│   ├── __main__.py              # python -m depu_img_mcp 入口
│   ├── server.py                # MCPServer 实例 + tool 注册
│   ├── config.py                # pydantic-settings，env+文件双源
│   ├── providers/
│   │   ├── __init__.py          # ProviderRegistry
│   │   ├── base.py              # BaseProvider 抽象
│   │   ├── openai_compat.py     # 任意 OpenAI 兼容端点（主力）
│   │   └── anthropic.py         # Anthropic 原生 /v1/messages（可选）
│   ├── image.py                 # 图片预处理：本地/URL/base64 统一、magic byte、SSRF、压缩
│   ├── prompts.py               # BASE_VISION_PROMPT + task_type 模板
│   ├── retry.py                 # 指数退避（429/5xx/网络）
│   └── web/
│       ├── __init__.py
│       ├── app.py               # FastAPI 后台（/admin 配置、/playground 测试）
│       └── templates/
│           └── admin.html       # 单页后台（Jinja2）
├── config.example.toml          # 配置示例
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml               # uv 管理
├── .env.example
└── README.md
```

## 4. 配置设计

双源：环境变量覆盖配置文件，配置文件覆盖默认值。配置文件路径 `DEPU_CONFIG_PATH`（默认 `/etc/depu/config.toml` 或项目根）。

### `config.example.toml`

```toml
[server]
transport = "streamable-http"   # streamable-http | stdio | sse
host = "0.0.0.0"
port = 8080
mcp_path = "/mcp"

[web]
enabled = true                  # 是否启用 /admin 后台
admin_token = ""                # 留空则本机可直接访问；远程需带 token

[prompt]
# 底层系统提示词，每次调用都会注入。设为空串可禁用。
base_vision_prompt = """You are a vision assistant. Describe the image accurately and concisely to assist a text-only model. Respond in the same language as the user's prompt."""

# 默认每路后端超时/重试
[request]
timeout_ms = 30000
max_retries = 3
backoff_base_ms = 500

[security]
max_image_bytes = 20_000_000     # 20MB
allow_local_file = true          # 是否允许读本地文件路径
ssrf_block_private = true        # 拉远程图时屏蔽私网

# 后端视觉模型，可配多个；命名 provider
[[providers]]
name = "default"
type = "openai-compat"           # openai-compat | anthropic
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = "${DASHSCOPE_API_KEY}" # 支持 ${ENV} 插值
model = "qwen3-vl-flash"
auth_header = "bearer"           # bearer | x-api-key | custom
auth_template = ""               # auth_header=custom 时用，支持 {{key}}
api_path = "/chat/completions"   # openai-compat 默认值
max_tokens = 2048

[[providers]]
name = "glm"
type = "openai-compat"
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key = "${ZHIPU_API_KEY}"
model = "glm-4.6v"

[[providers]]
name = "openai"
type = "openai-compat"
base_url = "https://api.openai.com/v1"
api_key = "${OPENAI_API_KEY}"
model = "gpt-4o"
```

### 关键环境变量（覆盖配置文件）

| 变量 | 作用 |
|---|---|
| `DEPU_CONFIG_PATH` | 配置文件路径 |
| `MCP_TRANSPORT` | 传输方式 |
| `MCP_HOST` / `MCP_PORT` | 监听地址 |
| `WEB_ENABLED` / `ADMIN_TOKEN` | 后台开关与鉴权 |
| `BASE_VISION_PROMPT` | 覆盖底层注入 prompt |
| `<PROVIDER>_API_KEY` | 各 provider 的密钥（避免写进文件） |
| `DEFAULT_PROVIDER` | 默认后端名 |

## 5. MCP 工具设计

暴露 2 个工具（参考 luma-mcp 的单工具主线 + vllm-mcp 的辅助工具）：

### `image_understand`（主工具）

```python
@mcp.tool()
async def image_understand(
    image: str,                       # 本地路径 / http(s) URL / data:image/...;base64,...
    prompt: str = "",                 # 用户问题；空则用 task_type 的默认描述
    task_type: str = "auto",          # auto|general|ocr|ui|debug|describe
    provider: str | None = None,      # 指定后端；None 用 DEFAULT_PROVIDER
    model: str | None = None,         # 覆盖 provider 的默认模型
    max_tokens: int | None = None,
) -> str:
    """Describe/analyze an image via a vision model. Use this when you cannot see images."""
```

**处理流程：**
1. `image.py` 归一化输入 → 校验格式（magic byte）/ 大小 / SSRF
2. 大图压缩（最长边 > 1568px 降采样，参考 luma-mcp 的截图保真策略）
3. `prompts.py` 按 `task_type` 选模板 + 拼 `base_vision_prompt` + 用户 `prompt`
4. `providers` 转发给视觉模型，`retry.py` 处理 429/5xx
5. 返回纯文本描述（结构化：描述 + 可读文字 + 警告，参考 visual-mcp 的输出结构）

### `list_vision_providers`

```python
@mcp.tool()
async def list_vision_providers() -> str:
    """List configured vision backends and their models."""
```

返回 JSON：各 provider 名称、type、model、是否可用（key 是否就绪）。

## 6. Provider 抽象

```python
class BaseProvider(ABC):
    name: str
    async def understand(self, image_b64: str, mime: str,
                         system_prompt: str, user_prompt: str,
                         model: str, max_tokens: int) -> str: ...

class OpenAICompatProvider(BaseProvider):
    # 走 /chat/completions，content 里塞 image_url
    # 支持 bearer / x-api-key / custom 鉴权头（参考 luma-mcp）

class AnthropicProvider(BaseProvider):
    # 走 /v1/messages，content 里塞 image block（base64）
    # 仅当用户后端是 Anthropic 原生 API 时启用
```

`ProviderRegistry` 按 `config.toml` 的 `[[providers]]` 实例化，按 name 索引。`DEFAULT_PROVIDER` 决定默认路由。

## 7. Web 后台（轻量，可裁剪）

**非强需求**，默认 `enabled=true` 但极简。单页 `admin.html` 两个区块：

- **配置区**：显示并编辑 `config.toml` 的关键字段（providers 列表、base_url、model、base_vision_prompt、task_type 默认值）。保存即写回 TOML 并热重载 provider 注册表。远程访问需带 `ADMIN_TOKEN`（query 或 header）。
- **测试场**：拖拽/选择图片 + 输入 prompt + 选 provider → 直接调 `image_understand` 看返回。等同于在线 playground，便于验证后端端点是否通。

实现：FastAPI 挂在 `/admin`，与 MCP 服务同进程不同路径（MCP 在 `/mcp`，后台在 `/admin`）。启动时若 `WEB_ENABLED=false` 则不挂载，零开销。

> 若后续完全不需要，设 `WEB_ENABLED=false` 即可，代码可后续剥离成独立微服务。

## 8. Docker 设计（强需求）

### `Dockerfile`（多阶段）

```dockerfile
FROM python:3.11-slim AS builder
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev
COPY src ./src
COPY config.example.toml ./

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/config.example.toml ./config.toml
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8080
# 默认 Streamable HTTP
CMD ["python", "-m", "depu_img_mcp"]
```

### `docker-compose.yml`

```yaml
services:
  depu-img-mcp:
    build: .
    ports:
      - "8080:8080"
    env_file: .env
    environment:
      - MCP_TRANSPORT=streamable-http
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8080
      - WEB_ENABLED=true
    volumes:
      - ./config.toml:/app/config.toml:ro
      - ./data:/app/data          # 可选：缓存/日志
    restart: unless-stopped
```

- 配置通过 volume 挂载，改配置后 `docker compose restart` 即生效
- 密钥通过 `.env` 注入，不进镜像
- 健康检查：`/mcp` 端点 + `/admin/health`

## 9. 安全要点

| 风险 | 措施（借鉴 VisionPower / luma-mcp） |
|---|---|
| SSRF | 拉远程图时解析 IP，屏蔽私网/环回/保留段，禁止重定向跟随 |
| 路径穿越 | 本地文件读取限制在工作目录白名单或显式 `allow_local_file` |
| 图片投毒 | magic byte 校验真实格式，限制最大字节数 |
| 密钥泄露 | 配置文件 `api_key` 支持 `${ENV}` 插值，密钥只走环境变量；日志脱敏 |
| 后台越权 | `/admin` 远程访问强制 `ADMIN_TOKEN`，本机可放行 |

## 10. 交付里程碑

| 阶段 | 内容 | 产出 |
|---|---|---|
| M1 | 骨架 + 单 provider（openai-compat）+ `image_understand` + stdio | 可用 stdio 跑通主链路 |
| M2 | Streamable HTTP 传输 + Docker + docker-compose | 容器化 HTTP 可调 |
| M3 | 多 provider + 配置双源 + `list_vision_providers` | 多后端可切换 |
| M4 | 图片预处理（SSRF/压缩/magic byte）+ 重试 + prompt 注入完善 | 生产可用 |
| M5 | 轻量 Web 后台（配置 + playground） | 可视化运维 |

## 11. 与参考项目的差异说明

- **比 vllm-mcp 多**：Web 后台、更完整的 prompt 双层注入、更严格的安全校验、更灵活的鉴权头
- **比 luma-mcp 多**：Docker、HTTP 传输、多 provider 配置文件化、Web 后台
- **比 luma-mcp 少（取舍）**：不预置 5 家国产模型硬编码，改为 `config.toml` 自由配置（更通用，但首次配置稍繁）
- **不做**：多后端并行竞速（vision-tool 风格）—— 增加复杂度与成本，默认单后端足矣，留作后续 `strategy=parallel` 选项
