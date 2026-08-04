# depu-img-mcp

图像理解 MCP 服务器 —— 让不支持图像的文本模型通过 MCP 协议把图片 + prompt 转发给视觉模型，返回描述文本。自身不做推理，是协议适配与转发层。专为 Docker 部署 + 企业内网服务设计。

## 特性

- **MCP v2**（Streamable HTTP，2026-07-28 规范）
- **Docker 部署**，开箱即用
- **任意 OpenAI 兼容后端**：LiteLLM 网关 / vLLM / OpenAI / DashScope / 智谱 / OpenRouter / Ollama 等
- **Web 后台** `/admin`：在线配置 provider、切换默认后端、编辑 prompt、测试图片
- **企业服务化**：客户端只能传图 + prompt，后端路由由 admin 统一控制
- 配置双源：环境变量覆盖 `config.toml`，密钥支持 `${ENV}` 插值

## 快速部署

镜像：`catmouse498/depu-img-mcp:latest`

### 方式一：config.toml + .env 文件（推荐，适合多 provider 配置）

**1. 准备配置文件**

```bash
# config.toml —— 配置视觉后端
cat > config.toml << 'EOF'
[server]
transport = "streamable-http"
host = "0.0.0.0"
port = 8080

[web]
enabled = true

[prompt]
base_vision_prompt = "你是一个视觉助手。请准确、简洁地描述图片，帮助无法看图的文本模型。"

[request]
timeout_ms = 30000
max_retries = 3
backoff_base_ms = 500

[security]
max_image_bytes = 20000000
allow_local_file = true
ssrf_block_private = true

[[providers]]
name = "default"
type = "openai-compat"
base_url = "https://your-vision-endpoint.com/v1"
api_key = "${VISION_API_KEY}"
model = "your-vision-model"
auth_header = "bearer"
api_path = "/chat/completions"
max_tokens = 2048
EOF

# .env —— 填入真实密钥（不进镜像，不提交 git）
cat > .env << 'EOF'
VISION_API_KEY=sk-your-real-api-key
ADMIN_TOKEN=your-admin-password
EOF
```

**2. 启动**

```bash
docker run -d \
  --name depu-img-mcp \
  -p 8080:8080 \
  -v $(pwd)/config.toml:/app/config.toml \
  --env-file .env \
  --restart unless-stopped \
  catmouse498/depu-img-mcp:latest
```

### 方式二：纯环境变量（适合单 provider、快速部署）

不用 config.toml，所有配置通过环境变量注入。镜像自带的 config.toml 用 `${ENV}` 引用，环境变量会自动填充。

```bash
docker run -d \
  --name depu-img-mcp \
  -p 8080:8080 \
  -e VISION_API_KEY=sk-your-real-api-key \
  -e ADMIN_TOKEN=your-admin-password \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_HOST=0.0.0.0 \
  -e MCP_PORT=8080 \
  -e WEB_ENABLED=true \
  --restart unless-stopped \
  catmouse498/depu-img-mcp:latest
```

> **注意**：纯 env 方式下，后端端点 URL 和 model 名仍需在 `config.toml` 里设置（因为它们不是预定义的环境变量）。如果你只用环境变量，需挂载一个改好 `base_url` 和 `model` 的 `config.toml`。最简单的做法还是用**方式一**。

### 方式三：docker-compose

```yaml
services:
  depu-img-mcp:
    image: catmouse498/depu-img-mcp:latest
    container_name: depu-img-mcp
    ports:
      - "8080:8080"
    env_file:
      - .env
    environment:
      - MCP_TRANSPORT=streamable-http
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8080
      - WEB_ENABLED=true
      - ADMIN_TOKEN=${ADMIN_TOKEN}
    volumes:
      - ./config.toml:/app/config.toml
    restart: unless-stopped
```

```bash
docker compose up -d
```

## 环境变量参考

| 变量 | 说明 | 默认值 |
|---|---|---|
| `MCP_TRANSPORT` | 传输方式：`streamable-http` / `stdio` / `sse` | `streamable-http` |
| `MCP_HOST` | 监听地址 | `0.0.0.0` |
| `MCP_PORT` | 监听端口 | `8080` |
| `MCP_PATH` | MCP 端点路径 | `/mcp` |
| `WEB_ENABLED` | 是否启用 Web 后台 | `true` |
| `ADMIN_TOKEN` | 后台登录密码（空则免密码） | `""` |
| `VISION_API_KEY` | 视觉后端 API key（被 config.toml 的 `${VISION_API_KEY}` 引用） | — |
| `BASE_VISION_PROMPT` | 覆盖底层系统提示词 | 内置中文默认值 |
| `DEFAULT_PROVIDER` | 默认后端名（覆盖 config.toml） | `default` |

## 访问

| 地址 | 用途 |
|---|---|
| `http://localhost:8080/mcp` | MCP 端点（客户端连接） |
| `http://localhost:8080/admin` | Web 后台（浏览器登录，密码 = `ADMIN_TOKEN`） |

## MCP 工具

只有一个工具，客户端只需传图 + 提问：

```
image_understand(image: str, prompt: str = "") -> str
```

- `image`：http(s) URL 或 `data:image/...;base64,...` URI（内联 base64）。**不支持本地文件路径**（Docker 部署，容器看不到客户端文件系统）
- `prompt`：想了解什么；空则给出通用描述

后端 provider 和 model 由 admin 通过后台配置，客户端不能指定。

## Claude Code 配置

```bash
claude mcp add --transport http depu-img http://localhost:8080/mcp
```

或在 `~/.claude.json`：

```json
{
  "mcpServers": {
    "depu-img": {
      "type": "http",
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

## 源码

https://github.com/luyufan498/depu-image-understand-mcp

## License

MIT
