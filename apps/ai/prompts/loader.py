"""Prompt files: apps/ai/prompts/<name>.md with a small front matter block.

    ---
    description: 一句话说明
    temperature: 0
    ---
    正文，用 {variable} 占位；字面的花括号写成 {{ }}。

Only "key: value" lines are supported in the front matter (no YAML dependency).
Non-string variables are rendered as JSON so lists and dicts read naturally.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    description: str
    temperature: float
    template: str

    def render(self, variables: dict) -> str:
        """Fill placeholders; a missing variable raises KeyError naming it."""
        values = {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for key, value in variables.items()
        }
        return self.template.format_map(values)


@cache
def load_prompt(name: str) -> Prompt:
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"prompt file not found: {path.name}")
    text = path.read_text(encoding="utf-8")
    meta, body = _split_front_matter(text)
    return Prompt(
        name=name,
        description=meta.get("description", ""),
        temperature=float(meta.get("temperature", 0)),
        template=body.strip() + "\n",
    )


def example_output(name: str) -> str:
    """Canned model output used by the mock client and tests."""
    path = PROMPT_DIR / f"{name}.example.json"
    if not path.is_file():
        raise PromptError(f"mock example not found: {path.name}")
    return path.read_text(encoding="utf-8")


def _split_front_matter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise PromptError("front matter is not closed with ---") from exc
    meta = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1:])
