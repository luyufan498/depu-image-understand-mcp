# depu-img-mcp

图像理解 MCP 服务器 —— 让不支持图像的文本模型通过 MCP 把图片 + prompt 转发给视觉模型，返回描述文本。自身不做推理，是协议适配与转发层。

## 特性

- **MCP v2**（`MCPServer` + Streamable HTTP，2026-07-28 规范），同时支持 stdio / SSE
- **Docker 部署**（多阶段构建 + docker-compose）
- **多后端 provider**：任意 OpenAI 兼容端点（LiteLLM 网关 / vLLM / OpenAI / DashScope / 智谱 / OpenRouter / Ollama …）
- **双层 prompt 注入**：全局 `base_vision_prompt` + per-call `prompt` + `task_type` 路由（auto/general/ocr/ui/debug/describe）
- **安全**：magic byte 校验、大小限制、SSRF 防护、路径白名单
- **轻量 Web 后台**（`/admin`）：查看配置 + 在线测试图片
- 配置双源：环境变量覆盖 `config.toml`，密钥支持 `${ENV}` 插值

## 快速开始

```bash
# 1. 准备 .env（至少填 ADMIN_TOKEN 和视觉后端 API key）
cp .env.example .env
# 编辑 .env 填入 API key

# 2. Docker 启动（首次会自动生成 ./conf/config.toml 默认配置）
docker compose up -d

# 3. 访问后台改配置（或直接编辑 ./conf/config.toml 后重启）
open http://localhost:8080/admin
# MCP 端点：http://localhost:8080/mcp
```

> 首次启动无需预先准备 `config.toml`：容器挂载 `./conf/` 目录，若里面没有配置文件，会自动从内置模板生成一份。之后可在 `/admin` 后台在线编辑，或直接改 `./conf/config.toml` 后 `docker compose restart`。

## 本地运行（开发）

```bash
uv sync
uv run python -m depu_img_mcp          # 默认 streamable-http
MCP_TRANSPORT=stdio uv run python -m depu_img_mcp   # stdio 模式给 Claude Desktop 等
```

## MCP 工具

### `image_understand`
```python
image_understand(
    image: str,            # http(s) URL 或 data:image/...;base64,... URI（内联 base64）。不支持本地文件路径（Docker 部署，容器看不到客户端文件系统）
    prompt: str = "",      # 用户问题；空则给出通用描述（物体、文字/OCR、布局、颜色等）
) -> str
```

> **provider / model 由后台 admin 统一配置**，客户端不能指定。这用于企业内网服务，后端路由由运维通过 `/admin` 后台决定。

只有一个工具。客户端传图 + prompt，服务器用后台配置的默认 provider 及其 model 进行视觉理解，返回文本描述。

## 配置示例

```toml
[[providers]]
name = "default"
type = "openai-compat"
base_url = "https://gateway.ai.depu.school/v1"
api_key = "${DEPU_GATEWAY_API_KEY}"
model = "Kimi-K2.7-Code"
auth_header = "bearer"
```

## 客户端配置（Claude Desktop 示例）

stdio 模式：
```json
{
  "mcpServers": {
    "depu-img": {
      "command": "python",
      "args": ["-m", "depu_img_mcp"],
      "env": { "MCP_TRANSPORT": "stdio", "DEPU_GATEWAY_API_KEY": "sk-..." }
    }
  }
}
```

HTTP 模式（支持远程 MCP 的客户端）：
```json
{
  "mcpServers": {
    "depu-img": { "url": "http://localhost:8080/mcp" }
  }
}
```

## License

MIT
