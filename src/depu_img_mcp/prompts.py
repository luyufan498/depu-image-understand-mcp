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
    "ocr": "提取图片中所有可见的文字，尽量保留原始排版。",
    "ui": "描述这个界面：布局、组件、可见的标签文字，以及它可能的用途。",
    "debug": "这是一张报错或调试截图，请详细描述其中的错误信息、堆栈、日志或任何诊断文本。",
    "describe": "请对图片给出详尽的通用描述：物体、人物、文字/OCR、布局、颜色及值得注意的细节。",
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
        system = f"{system}\n\n任务指引：{task_template}"
    elif task_template:
        system = task_template

    if user_prompt:
        final_user = user_prompt
    elif task_template:
        final_user = task_template
    else:
        final_user = ""  # provider will fall back to a describe prompt

    return system, final_user
