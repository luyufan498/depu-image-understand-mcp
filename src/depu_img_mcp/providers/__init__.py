"""Provider registry — instantiates providers from config, indexes by name."""
from __future__ import annotations

import logging

from ..config import AppConfig, ProviderConfig
from .base import BaseProvider
from .openai_compat import OpenAICompatProvider

log = logging.getLogger("depu.providers")


def build_provider(pc: ProviderConfig) -> BaseProvider:
    if pc.type == "openai-compat":
        return OpenAICompatProvider(
            name=pc.name,
            base_url=pc.base_url,
            api_key=pc.api_key,
            model=pc.model,
            auth_header=pc.auth_header,
            auth_template=pc.auth_template,
            api_path=pc.api_path,
            max_tokens=pc.max_tokens,
        )
    if pc.type == "anthropic":
        # Placeholder — Anthropic native API uses a different content shape.
        # Implemented in a follow-up; fall back to openai-compat through a proxy.
        raise NotImplementedError(
            f"provider type 'anthropic' not yet implemented for '{pc.name}'. "
            "Use a LiteLLM/OpenRouter proxy with type='openai-compat' instead."
        )
    raise ValueError(f"unknown provider type '{pc.type}' for '{pc.name}'")


class ProviderRegistry:
    def __init__(self, cfg: AppConfig):
        self._providers: dict[str, BaseProvider] = {}
        for pc in cfg.providers:
            try:
                self._providers[pc.name] = build_provider(pc)
            except Exception as e:  # noqa: BLE001 - keep other providers alive
                log.error("failed to build provider '%s': %s", pc.name, e)
        self.default_name = cfg.default_provider

    def get(self, name: str | None = None) -> BaseProvider:
        key = name or self.default_name
        if key not in self._providers:
            available = ", ".join(self._providers) or "(none)"
            raise KeyError(
                f"provider '{key}' not configured. Available: {available}"
            )
        return self._providers[key]

    def list_providers(self) -> list[dict]:
        return [
            {"name": p.name, "model": p.model, "available": p.available}
            for p in self._providers.values()
        ]

    def __len__(self) -> int:
        return len(self._providers)
