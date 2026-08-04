"""Prompt assembly: base system prompt + per-call user prompt.

The base vision prompt (configured by the admin) frames every call. The
caller's prompt asks the specific question. When the caller sends no prompt,
a general-description fallback is used so the model still produces a useful
answer.
"""
from __future__ import annotations

from .config import PromptConfig

# Fallback user prompt when the caller sends an empty prompt.
_FALLBACK_PROMPT = "请对图片给出详尽的通用描述：物体、人物、文字/OCR、布局、颜色及值得注意的细节。"


def build_prompts(
    user_prompt: str,
    prompt_cfg: PromptConfig,
) -> tuple[str, str]:
    """Return (system_prompt, final_user_prompt).

    system_prompt = the admin-configured base_vision_prompt (may be empty).
    final_user_prompt = the caller's prompt, or a general-description
                       fallback if the caller sent nothing.
    """
    system = prompt_cfg.base_vision_prompt
    final_user = user_prompt if user_prompt else _FALLBACK_PROMPT
    return system, final_user
