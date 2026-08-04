"""Provider abstraction for vision backends."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """A vision backend that takes an image + prompts and returns text."""

    name: str
    model: str

    @abstractmethod
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
        """Return the vision model's text description of the image."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Whether this provider has the credentials needed to run."""
        return bool(getattr(self, "api_key", ""))
