"""Lightweight web admin: view config + test images in a playground.

Mounted into the same ASGI app as the MCP server (see server.run). Designed to
be minimal — a single page with config display/edit and an image test box.

Auth: a single shared password (ADMIN_TOKEN in config). Visiting /admin/ without
a valid session cookie shows a login page; submitting the password sets a cookie
and admits the browser. The /mcp endpoint and playground API calls are NOT
gated — ADMIN_TOKEN only guards the admin UI entry. Per-request API keys / IDC
gateway routing are handled elsewhere (TODO).
"""
from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import AppConfig

_BASE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(_BASE / "templates"))

# In-memory store of issued session tokens. Single-process server, so this is
# fine; restart logs everyone out (acceptable for a light admin console).
_SESSIONS: set[str] = set()


def _check_auth(cfg: AppConfig, request: Request) -> bool:
    """Return True if the request carries a valid admin session cookie."""
    if not cfg.web.admin_token:
        return True  # no password configured → open access
    tok = request.cookies.get("depu_admin")
    return bool(tok) and tok in _SESSIONS


def build_admin_app(cfg: AppConfig) -> FastAPI:
    app = FastAPI(title="depu-img-mcp admin", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if not _check_auth(cfg, request):
            # show login page
            return TEMPLATES.TemplateResponse(
                request, "login.html", {"needs_token": bool(cfg.web.admin_token)}
            )
        return TEMPLATES.TemplateResponse(
            request,
            "admin.html",
            {"config": cfg, "providers": cfg.providers},
        )

    @app.post("/login")
    async def login(request: Request):
        if not cfg.web.admin_token:
            return RedirectResponse(url="./", status_code=303)
        body = await request.json()
        password = body.get("password", "")
        if hmac.compare_digest(password, cfg.web.admin_token):
            tok = secrets.token_urlsafe(24)
            _SESSIONS.add(tok)
            resp = JSONResponse({"ok": True})
            resp.set_cookie(
                "depu_admin", tok, httponly=True, samesite="lax",
                max_age=60 * 60 * 24 * 7,  # 7 days
            )
            return resp
        return JSONResponse({"error": "密码错误"}, status_code=401)

    @app.post("/logout")
    async def logout(request: Request):
        tok = request.cookies.get("depu_admin")
        if tok:
            _SESSIONS.discard(tok)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("depu_admin")
        return resp

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # ---- APIs below are NOT gated by admin token (per design) ----
    # API keys / IDC gateway routing will be handled at a different layer.

    @app.get("/api/config")
    async def api_config(request: Request):
        # Don't leak full api keys — mask them.
        provs = []
        for p in cfg.providers:
            d = p.model_dump()
            has_key = bool(d.get("api_key"))
            if has_key:
                k = d["api_key"]
                d["api_key"] = k[:6] + "…" + k[-4:] if len(k) > 12 else "***"
            d["available"] = has_key
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
