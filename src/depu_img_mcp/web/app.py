"""Lightweight web admin: view config + test images in a playground.

Mounted into the same ASGI app as the MCP server (see server.run). Designed to
be minimal — a single page with config display/edit and an image test box.

Auth: if ADMIN_TOKEN is set, requests from non-localhost must carry it as
?token=... or Authorization: Bearer ....  Localhost is allowed without token.
"""
from __future__ import annotations

import socket
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..config import AppConfig

_BASE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(_BASE / "templates"))


def _is_local(host: str) -> bool:
    try:
        addr = socket.getaddrinfo(host, None)[0][4][0]
        return addr in ("127.0.0.1", "::1")
    except (OSError, IndexError):
        return False


def _check_auth(cfg: AppConfig, request: Request) -> None:
    token = cfg.web.admin_token
    if not token:
        return
    client_host = request.client.host if request.client else ""
    if _is_local(client_host):
        return
    provided = request.query_params.get("token") or ""
    if not provided:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            provided = auth[7:]
    if provided != token:
        raise HTTPException(status_code=401, detail="admin token required")


def build_admin_app(cfg: AppConfig) -> FastAPI:
    app = FastAPI(title="depu-img-mcp admin", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        _check_auth(cfg, request)
        return TEMPLATES.TemplateResponse(
            request,
            "admin.html",
            {"config": cfg, "providers": cfg.providers},
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/config")
    async def api_config(request: Request):
        _check_auth(cfg, request)
        # Don't leak full api keys — mask them.
        provs = []
        for p in cfg.providers:
            d = p.model_dump()
            if d.get("api_key"):
                k = d["api_key"]
                d["api_key"] = k[:6] + "…" + k[-4:] if len(k) > 12 else "***"
            provs.append(d)
        return {
            "server": cfg.server.model_dump(),
            "web": cfg.web.model_dump(),
            "prompt": cfg.prompt.model_dump(),
            "default_provider": cfg.default_provider,
            "providers": provs,
        }

    @app.post("/api/test")
    async def api_test(request: Request):
        """Playground: run image_understand directly from the admin page."""
        _check_auth(cfg, request)
        body = await request.json()
        image = body.get("image", "")
        prompt = body.get("prompt", "")
        task_type = body.get("task_type", "auto")
        provider = body.get("provider")
        if not image:
            return JSONResponse({"error": "image required"}, status_code=400)

        from ..image import ImageError, load_image
        from ..prompts import build_prompts
        from ..providers import ProviderRegistry

        registry = ProviderRegistry(cfg)
        try:
            img = await load_image(image, cfg.security)
            prov = registry.get(provider)
            system_prompt, user_prompt = build_prompts(prompt, task_type, cfg.prompt)
            result = await prov.understand(
                image_b64=img.b64,
                mime_type=img.mime_type,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout_ms=cfg.request.timeout_ms,
                max_retries=cfg.request.max_retries,
                backoff_base_ms=cfg.request.backoff_base_ms,
            )
            return {"result": result}
        except (ImageError, KeyError, Exception) as e:  # noqa: BLE001 - surface as 400
            return JSONResponse({"error": str(e)}, status_code=400)

    return app


def mount_admin(mcp_app, admin: FastAPI, cfg: AppConfig) -> None:
    """Mount the admin FastAPI under /admin on the MCP Starlette app."""
    from starlette.routing import Mount

    mcp_app.routes.append(Mount("/admin", app=admin))
