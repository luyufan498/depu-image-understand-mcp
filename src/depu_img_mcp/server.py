"""MCP server: tool registration and transport dispatch.

Uses the official MCP SDK v2 (MCPServer). Exposes two tools:
  - image_understand: forward an image + prompt to a vision backend
  - list_vision_providers: list configured backends

Transport is selected via config (streamable-http default, stdio and sse also
supported). When running over HTTP, a lightweight web admin can be mounted at
/admin in the same process.
"""
from __future__ import annotations

import json
import logging
import os

from mcp.server import MCPServer

from .config import AppConfig, load_config
from .image import ImageError, load_image
from .prompts import VALID_TASK_TYPES, build_prompts
from .providers import ProviderRegistry

log = logging.getLogger("depu.server")


def create_mcp_server(cfg: AppConfig) -> tuple[MCPServer, ProviderRegistry]:
    """Build an MCPServer with tools registered, bound to the given config.

    Returns (mcp, registry) so the caller can hot-reload the registry from the
    admin UI without rebuilding the MCP server.
    """
    registry = ProviderRegistry(cfg)
    if len(registry) == 0:
        log.warning(
            "no vision providers configured — image_understand will fail "
            "until a provider is added in config.toml"
        )

    mcp = MCPServer(
        name="depu-img-mcp",
        version="0.1.0",
        instructions=(
            "Image understanding proxy. Use `image_understand` to analyze any "
            "image via a vision model when you cannot see images directly. "
            "Use `list_vision_providers` to see configured backends."
        ),
    )

    @mcp.tool()
    async def image_understand(
        image: str,
        prompt: str = "",
        task_type: str = "auto",
        provider: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Describe or analyze an image using a vision model.

        Call this whenever you need to understand an image you cannot see.

        Args:
            image: The image as a local file path, an http(s) URL, a
                data:image/...;base64,... URI, or a raw base64 string.
            prompt: What you want to know about the image. Empty = general
                description guided by task_type.
            task_type: auto | general | ocr | ui | debug | describe. Hints the
                kind of analysis when prompt is empty or terse.
            provider: Name of a configured backend. None = default provider.
            model: Override the provider's default model.
            max_tokens: Override the provider's default max output tokens.

        Returns:
            The vision model's text description of the image.
        """
        if task_type not in VALID_TASK_TYPES:
            return f"Error: task_type must be one of {sorted(VALID_TASK_TYPES)}, got '{task_type}'"

        try:
            img = await load_image(image, cfg.security)
        except ImageError as e:
            return f"Error loading image: {e}"

        try:
            prov = registry.get(provider)
        except KeyError as e:
            return f"Error: {e}"

        system_prompt, user_prompt = build_prompts(prompt, task_type, cfg.prompt)

        try:
            result = await prov.understand(
                image_b64=img.b64,
                mime_type=img.mime_type,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                max_tokens=max_tokens,
                timeout_ms=cfg.request.timeout_ms,
                max_retries=cfg.request.max_retries,
                backoff_base_ms=cfg.request.backoff_base_ms,
            )
        except Exception as e:
            log.exception("vision backend call failed")
            return f"Error from vision backend: {e}"

        return result

    @mcp.tool()
    async def list_vision_providers() -> str:
        """List configured vision backends and their models.

        Returns a JSON string of provider names, models, and availability.
        """
        return json.dumps(
            {"default": registry.default_name, "providers": registry.list_providers()},
            ensure_ascii=False,
            indent=2,
        )

    return mcp, registry


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def run(cfg: AppConfig | None = None) -> None:
    """Load config, build server, and run with the configured transport."""
    cfg = cfg or load_config()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    mcp, registry = create_mcp_server(cfg)

    transport = cfg.server.transport
    log.info("starting depu-img-mcp (transport=%s)", transport)

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    if transport in ("streamable-http", "sse"):
        if cfg.web.enabled:
            # Mount admin into the same ASGI app so /mcp and /admin coexist.
            from .web.app import build_admin_app, mount_admin
            mcp_app = mcp.streamable_http_app(
                streamable_http_path=cfg.server.mcp_path,
                # Images base64 can be large; raise the default 4MB ceiling.
                max_request_body_size=64 * 1024 * 1024,
                host=cfg.server.host,
            )
            admin = build_admin_app(cfg, registry)
            mount_admin(mcp_app, admin, cfg)
            import uvicorn
            uvicorn.run(mcp_app, host=cfg.server.host, port=cfg.server.port)
        else:
            # Let the SDK run its own ASGI app.
            mcp.run(
                transport=transport,
                host=cfg.server.host,
                port=cfg.server.port,
                streamable_http_path=cfg.server.mcp_path,
            )
        return

    raise ValueError(f"unknown transport: {transport}")
