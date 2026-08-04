"""OpenAI-compatible vision provider.

Works with any endpoint that speaks OpenAI Chat Completions with image_url
content blocks: OpenAI, LiteLLM gateways, vLLM, DashScope compat-mode,
Zhipu, OpenRouter, Ollama (OpenAI shape), etc.
"""
from __future__ import annotations

import json
import logging

import httpx

from ..retry import request_with_retry
from .base import BaseProvider

log = logging.getLogger("depu.provider.openai")


class OpenAICompatProvider(BaseProvider):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        auth_header: str = "bearer",
        auth_template: str = "",
        api_path: str = "/chat/completions",
        max_tokens: int = 2048,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.auth_header = auth_header
        self.auth_template = auth_template
        self.api_path = api_path or "/chat/completions"
        self.default_max_tokens = max_tokens

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _auth_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.auth_header == "bearer":
            h["Authorization"] = f"Bearer {self.api_key}"
        elif self.auth_header == "x-api-key":
            h["x-api-key"] = self.api_key
        elif self.auth_header == "custom":
            tmpl = self.auth_template or "Bearer {{key}}"
            h["Authorization"] = tmpl.replace("{{key}}", self.api_key)
        return h

    async def understand(
        self,
        image_b64: str,
        mime_type: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout_ms: int = 30000,
        max_retries: int = 3,
        backoff_base_ms: int = 500,
    ) -> str:
        url = self.base_url + self.api_path
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        data_url = f"data:{mime_type};base64,{image_b64}"
        user_content: list[dict] = []
        if user_prompt:
            user_content.append({"type": "text", "text": user_prompt})
        user_content.append({"type": "image_url", "image_url": {"url": data_url}})
        # If no user text, still send a minimal text so the model knows the task.
        if not user_prompt:
            user_content.insert(0, {"type": "text", "text": "请描述这张图片。"})
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.default_max_tokens,
        }
        headers = {**self._auth_headers(), "Content-Type": "application/json"}

        async with httpx.AsyncClient() as client:
            resp = await request_with_retry(
                client, "POST", url,
                json=payload, headers=headers,
                timeout=timeout_ms / 1000,
                max_retries=max_retries, backoff_base_ms=backoff_base_ms,
            )
        if resp.status_code >= 400:
            log.error("provider %s error %s: %s", self.name,
                      resp.status_code, resp.text[:500])
            raise RuntimeError(
                f"vision backend '{self.name}' returned {resp.status_code}: "
                f"{resp.text[:300]}"
            )
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise RuntimeError(
                f"unexpected response shape from '{self.name}': {e}"
            ) from e
