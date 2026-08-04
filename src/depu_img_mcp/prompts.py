"""Prompt assembly: base system prompt + task_type templates + per-call prompt.

Borrowed from luma-mcp's two-layer design: a global base prompt that frames the
vision task, plus per-call task templates that nudge the model toward the right
kind of answer when the caller's prompt is empty or terse.
"""
from __future__ import annotations

from .config import PromptConfig

# Task-type templates. When the user prompt is empty, these guide the model.
# When the user prompt is present, the template is still prepended lightly so
# the model understands the requested *kind* of analysis.
TASK_TEMPLATES: dict[str, str] = {
    "general": "",
    "ocr": "Extract all visible text from the image. Preserve layout where possible.",
    "ui": "Describe the UI: layout, components, visible labels, and apparent purpose.",
    "debug": "This is a screenshot of an error or debug screen. Describe the error, "
             "stack trace, logs, or any diagnostic text in detail.",
    "describe": "Give a thorough general description: objects, people, text/OCR, "
                "layout, colors, and notable details.",
    "auto": "",  # let the user prompt (or describe default) drive
}

VALID_TASK_TYPES = set(TASK_TEMPLATES) | {"auto"}


def build_prompts(
    user_prompt: str,
    task_type: str,
    prompt_cfg: PromptConfig,
) -> tuple[str, str]:
    """Return (system_prompt, final_user_prompt).

    system_prompt = base_vision_prompt (+ task template appended if present)
    final_user_prompt = user_prompt, or the task template if user_prompt empty,
                       or a describe fallback if both empty.
    """
    task_type = task_type if task_type in TASK_TEMPLATES else "general"
    task_template = TASK_TEMPLATES[task_type]

    system = prompt_cfg.base_vision_prompt
    if task_template and system:
        system = f"{system}\n\nTask guidance: {task_template}"
    elif task_template:
        system = task_template

    if user_prompt:
        final_user = user_prompt
    elif task_template:
        final_user = task_template
    else:
        final_user = ""  # provider will fall back to "Describe this image."

    return system, final_user
