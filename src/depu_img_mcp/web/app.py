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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import AppConfig, ProviderConfig, save_config
from ..providers import ProviderRegistry

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


def build_admin_app(cfg: AppConfig, registry: ProviderRegistry) -> FastAPI:
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
        # Requires login — returns full api keys so the admin UI can show them
        # via a password field + eye toggle (no per-refresh masking drift).
        if not _check_auth(cfg, request):
            raise HTTPException(status_code=401, detail="login required")
        provs = []
        for p in cfg.providers:
            d = p.model_dump()
            d["api_key_set"] = bool(d.get("api_key"))
            d["available"] = bool(d.get("api_key"))
            provs.append(d)
        return {
            "server": cfg.server.model_dump(),
            "web": cfg.web.model_dump(),
            "prompt": cfg.prompt.model_dump(),
            "request": cfg.request.model_dump(),
            "security": cfg.security.model_dump(),
            "default_provider": cfg.default_provider,
            "providers": provs,
        }

    @app.post("/api/config")
    async def api_config_save(request: Request):
        """Save full config: update cfg in place, hot-reload registry, write TOML."""
        if not _check_auth(cfg, request):
            raise HTTPException(status_code=401, detail="login required")
        body = await request.json()

        # Build new provider configs.
        new_providers: list[ProviderConfig] = []
        for rp in body.get("providers", []):
            try:
                new_providers.append(ProviderConfig(
                    name=rp["name"],
                    type=rp.get("type", "openai-compat"),
                    base_url=rp["base_url"],
                    api_key=rp.get("api_key", ""),
                    model=rp["model"],
                    auth_header=rp.get("auth_header", "bearer"),
                    auth_template=rp.get("auth_template", ""),
                    api_path=rp.get("api_path", "/chat/completions"),
                    max_tokens=int(rp.get("max_tokens", 2048)),
                ))
            except Exception as e:  # noqa: BLE001 - surface provider validation errors
                return JSONResponse(
                    {"error": f"provider '{rp.get('name','?')}': {e}"},
                    status_code=400,
                )

        # Update cfg in place
        cfg.providers = new_providers
        cfg.default_provider = body.get("default_provider", cfg.default_provider)
        if "prompt" in body:
            cfg.prompt.base_vision_prompt = body["prompt"].get("base_vision_prompt", cfg.prompt.base_vision_prompt)
        if "request" in body:
            cfg.request.timeout_ms = int(body["request"].get("timeout_ms", cfg.request.timeout_ms))
            cfg.request.max_retries = int(body["request"].get("max_retries", cfg.request.max_retries))
            cfg.request.backoff_base_ms = int(body["request"].get("backoff_base_ms", cfg.request.backoff_base_ms))
        if "security" in body:
            cfg.security.max_image_bytes = int(body["security"].get("max_image_bytes", cfg.security.max_image_bytes))
            cfg.security.allow_local_file = bool(body["security"].get("allow_local_file", cfg.security.allow_local_file))
            cfg.security.ssrf_block_private = bool(body["security"].get("ssrf_block_private", cfg.security.ssrf_block_private))

        # Hot-reload registry + persist
        registry.reload(cfg)
        try:
            save_config(cfg)
        except Exception as e:  # noqa: BLE001 - don't fail the whole save on write error
            return JSONResponse(
                {"ok": True, "warning": f"已生效但写回文件失败: {e}"},
                status_code=200,
            )
        return {"ok": True}

    @app.post("/api/test")
    async def api_test(request: Request):
        """Playground: run image_understand directly from the admin page."""
        body = await request.json()
        image = body.get("image", "")
        prompt = body.get("prompt", "")
        provider = body.get("provider")
        if not image:
            return JSONResponse({"error": "image required"}, status_code=400)

        from ..image import ImageError, load_image
        from ..prompts import build_prompts

        try:
            img = await load_image(image, cfg.security)
            prov = registry.get(provider)
            system_prompt, user_prompt = build_prompts(prompt, cfg.prompt)
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
