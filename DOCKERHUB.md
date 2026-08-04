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

> **首次启动无需预建配置文件**。把一个空目录挂到 `/app/conf`，容器首次启动会自动从内置模板生成 `config.toml`，之后可在 `/admin` 后台在线编辑，或直接改宿主机上的文件后重启。
>
> ⚠️ **务必挂载目录，不要挂载单个 `config.toml` 文件**。若宿主机上该文件还不存在，Docker 会把它当成目录创建，容器内 `/app/conf/config.toml` 变成空目录，服务启动即崩。挂载目录则没有这个问题。
>
> 🔒 **非 root 运行 + 文件属主匹配宿主机**。容器以非 root 用户 `depu`（默认 uid/gid 1000）运行，生成的配置和数据文件属主是这个 uid，宿主机上 uid 1000 的用户可直接编辑。若你的宿主机用户 uid 不是 1000，用 `PUID` / `PGID` 环境变量指定（见下方环境变量表）。

### 方式一：挂载目录 + .env（推荐）

```bash
# 1. 准备 .env（填密钥，不进镜像）
cat > .env << 'EOF'
VISION_API_KEY=sk-your-real-api-key
ADMIN_TOKEN=your-admin-password
EOF

# 2. 建一个空配置目录并启动（首次会自动生成 conf/config.toml）
mkdir -p conf
docker run -d \
  --name depu-img-mcp \
  -p 8080:8080 \
  -v $(pwd)/conf:/app/conf \
  --env-file .env \
  --restart unless-stopped \
  catmouse498/depu-img-mcp:latest

# 3. 启动后编辑 conf/config.toml 指向你的视觉后端，或访问 /admin 在线改
#    docker restart depu-img-mcp 让文件改动生效
```

如果想预先写好配置再启动，把 `config.example.toml` 复制进 `conf/config.toml` 改好即可，容器检测到文件已存在就不会覆盖。

### 方式二：环境变量 + 目录挂载（适合单 provider、快速部署）

挂载配置目录（首次自动生成 `config.toml`），密钥和传输参数走环境变量。镜像内置的默认 `config.toml` 用 `${ENV}` 引用，环境变量自动填充。

```bash
mkdir -p conf
docker run -d \
  --name depu-img-mcp \
  -p 8080:8080 \
  -v $(pwd)/conf:/app/conf \
  -e VISION_API_KEY=sk-your-real-api-key \
  -e ADMIN_TOKEN=your-admin-password \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_HOST=0.0.0.0 \
  -e MCP_PORT=8080 \
  -e WEB_ENABLED=true \
  --restart unless-stopped \
  catmouse498/depu-img-mcp:latest
```

> **注意**：后端端点 `base_url` 和 `model` 名不是预定义的环境变量，仍需在 `conf/config.toml` 里设置。首次启动后容器会自动生成默认 `config.toml`，编辑其中的 `base_url` 和 `model` 后 `docker restart depu-img-mcp` 即可，或直接进 `/admin` 后台改。

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
      - ./conf:/app/conf
    restart: unless-stopped
```

```bash
mkdir -p conf          # 首次可为空，容器会自动生成 config.toml
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
| `DEPU_CONFIG_PATH` | 配置文件路径（首次不存在时自动生成） | `/app/conf/config.toml` |
| `DEPU_CONFIG_DIR` | 配置目录（entrypoint 用来定位/创建配置） | `/app/conf` |
| `PUID` / `PGID` | 容器运行用户 uid/gid，决定生成文件的属主。设成你宿主机用户的 uid/gid，挂出来的文件就能直接编辑 | `1000` / `1000` |

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
