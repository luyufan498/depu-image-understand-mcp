"""Configuration: env vars override config file (TOML) override defaults.

Supports ${ENV_VAR} interpolation for secret fields in the TOML file so keys
never have to be committed.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_ENV_INTERP = re.compile(r"\$\{([A-Z0-9_]+)\}")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ServerConfig(BaseModel):
    transport: Literal["streamable-http", "stdio", "sse"] = "streamable-http"
    host: str = "0.0.0.0"
    port: int = 8080
    mcp_path: str = "/mcp"


class WebConfig(BaseModel):
    enabled: bool = True
    admin_token: str = ""


class PromptConfig(BaseModel):
    base_vision_prompt: str = (
        "你是一个视觉助手。请准确、简洁地描述/分析图片，以帮助一个无法看到图片的纯文本模型。"
        "如果用户的提示为空，请给出详尽的通用描述（物体、文字/OCR、布局、颜色等）。"
        "请使用与用户提示相同的语言回答。"
    )


class RequestConfig(BaseModel):
    timeout_ms: int = 30000
    max_retries: int = 3
    backoff_base_ms: int = 500


class SecurityConfig(BaseModel):
    max_image_bytes: int = 20_000_000
    allow_local_file: bool = True
    ssrf_block_private: bool = True


class ProviderConfig(BaseModel):
    name: str
    type: Literal["openai-compat", "anthropic"] = "openai-compat"
    base_url: str
    api_key: str = ""
    model: str
    auth_header: Literal["bearer", "x-api-key", "custom"] = "bearer"
    auth_template: str = ""       # used when auth_header == "custom"; supports {{key}}
    api_path: str = "/chat/completions"
    max_tokens: int = 2048


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    request: RequestConfig = Field(default_factory=RequestConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    default_provider: str = "default"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def _interpolate(value: str) -> str:
    """Replace ${ENV_VAR} with the env value; leave blank if unset."""
    def _sub(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), "")

    return _ENV_INTERP.sub(_sub, value)


def _apply_env_overrides(cfg: AppConfig) -> AppConfig:
    """Env vars win over file values."""
    if v := os.environ.get("MCP_TRANSPORT"):
        cfg.server.transport = v  # type: ignore[assignment]
    if v := os.environ.get("MCP_HOST"):
        cfg.server.host = v
    if v := os.environ.get("MCP_PORT"):
        cfg.server.port = int(v)
    if v := os.environ.get("MCP_PATH"):
        cfg.server.mcp_path = v
    if v := os.environ.get("WEB_ENABLED"):
        cfg.web.enabled = v.lower() in ("1", "true", "yes")
    if v := os.environ.get("ADMIN_TOKEN"):
        cfg.web.admin_token = v
    if v := os.environ.get("DEFAULT_PROVIDER"):
        cfg.default_provider = v
    if v := os.environ.get("BASE_VISION_PROMPT"):
        cfg.prompt.base_vision_prompt = v
    return cfg


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from TOML file, then apply env overrides."""
    path = Path(path) if path else _default_config_path()
    cfg = AppConfig()
    if path.exists():
        with path.open("rb") as f:
            raw = tomllib.load(f)
        # interpolate ${ENV} in string values, then build typed config
        for section, data in raw.items():
            if section == "providers":
                continue
            for k, v in data.items():
                if isinstance(v, str):
                    data[k] = _interpolate(v)
        providers_raw = raw.get("providers", [])
        for p in providers_raw:
            for k, v in p.items():
                if isinstance(v, str):
                    p[k] = _interpolate(v)
        cfg = AppConfig(**raw)
    return _apply_env_overrides(cfg)


def _default_config_path() -> Path:
    env_path = os.environ.get("DEPU_CONFIG_PATH", "")
    candidates = [
        Path(env_path) if env_path else None,
        Path.cwd() / "config.toml",
        Path.cwd() / "config.example.toml",
    ]
    for c in candidates:
        if c and c.is_file():
            return c
    return Path.cwd() / "config.toml"
