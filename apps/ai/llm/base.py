"""LLM client contract (docs/architecture.html §7.4).

Business code calls apps.ai.llm.factory.get_client() and uses three methods:

    result, task = client.extract_json(prompt_name=..., variables=..., schema=Model)
    text, task   = client.generate_text(prompt_name=..., variables=...)
    result, task = client.describe_image(prompt_name=..., image_bytes=..., schema=Model)

Failure contract (chosen for M13): every failure raises LLMError, whose .task is
the saved AITask (status "error" for API/network failures, "invalid_json" when the
output still can't be parsed or validated after one retry). Callers catch
LLMError and show a message; nothing reaches the user as a 500. Returning a
status instead was rejected because every caller would have to remember to
check for None.

Every call, successful or not, writes exactly one AITask. Only a digest and the
first 500 characters of the prompt are stored.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass

from pydantic import BaseModel

from ..models import AITask
from ..prompts.loader import load_prompt

MAX_ATTEMPTS = 2  # first try + one retry with the parse error fed back
PREVIEW_CHARS = 500
MAX_OUTPUT_CHARS = 20_000
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMError(Exception):
    def __init__(self, message: str, task: AITask):
        super().__init__(message)
        self.task = task


@dataclass
class Completion:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class BaseLLMClient:
    """Shared flow; subclasses implement _complete() and set provider / api_errors."""

    provider = "base"
    api_errors: tuple[type[BaseException], ...] = ()

    def model_name(self, *, image: bool) -> str:
        raise NotImplementedError

    def _complete(
        self, *, prompt_name: str, prompt: str, temperature: float, image_bytes: bytes | None,
        want_json: bool, history: list[tuple[str, str]],
    ) -> Completion:
        """Send one request. history holds (previous bad output, error) pairs for retries."""
        raise NotImplementedError

    # --- public API ---------------------------------------------------------------------

    def extract_json(self, *, prompt_name: str, variables: dict, schema: type[BaseModel]):
        return self._structured(prompt_name, variables, schema, image_bytes=None)

    def describe_image(
        self, *, prompt_name: str, image_bytes: bytes, variables: dict | None = None,
        schema: type[BaseModel],
    ):
        return self._structured(prompt_name, variables or {}, schema, image_bytes=image_bytes)

    def generate_text(self, *, prompt_name: str, variables: dict) -> tuple[str, AITask]:
        prompt = load_prompt(prompt_name)
        text = prompt.render(variables)
        call = _Call(self, prompt_name, text, image_bytes=None)
        try:
            completion = self._complete(
                prompt_name=prompt_name, prompt=text, temperature=prompt.temperature,
                image_bytes=None, want_json=False, history=[],
            )
        except self.api_errors as exc:
            task = call.save(AITask.Status.ERROR, error=exc)
            raise LLMError(f"模型调用失败：{exc}", task) from exc
        call.add(completion)
        return completion.text, call.save(AITask.Status.OK, output=completion.text)

    # --- shared structured flow -----------------------------------------------------------

    def _structured(self, prompt_name, variables, schema, *, image_bytes):
        prompt = load_prompt(prompt_name)
        text = prompt.render(variables)
        call = _Call(self, prompt_name, text, image_bytes=image_bytes)
        history: list[tuple[str, str]] = []
        for _ in range(MAX_ATTEMPTS):
            try:
                completion = self._complete(
                    prompt_name=prompt_name, prompt=text, temperature=prompt.temperature,
                    image_bytes=image_bytes, want_json=True, history=history,
                )
            except self.api_errors as exc:
                task = call.save(AITask.Status.ERROR, error=exc)
                raise LLMError(f"模型调用失败：{exc}", task) from exc
            call.add(completion)
            try:
                result = schema.model_validate(parse_json(completion.text))
            except ValueError as exc:  # JSONDecodeError and pydantic ValidationError
                history.append((completion.text, _short(exc)))
                continue
            return result, call.save(AITask.Status.OK, output=completion.text)

        bad_output, error = history[-1]
        task = call.save(AITask.Status.INVALID_JSON, output=bad_output, error=error)
        raise LLMError("模型输出无法解析，已重试一次仍失败。", task)


class _Call:
    """Collects attempts, tokens and timing for one logical call, then saves an AITask."""

    def __init__(self, client: BaseLLMClient, prompt_name: str, text: str, image_bytes):
        self.client, self.prompt_name, self.text, self.image_bytes = (
            client, prompt_name, text, image_bytes,
        )
        self.started = time.monotonic()
        self.attempts = self.prompt_tokens = self.completion_tokens = 0

    def add(self, completion: Completion) -> None:
        self.attempts += 1
        self.prompt_tokens += completion.prompt_tokens
        self.completion_tokens += completion.completion_tokens

    def save(self, status: str, *, output: str = "", error: BaseException | str = "") -> AITask:
        digest = hashlib.sha256(self.text.encode() + (self.image_bytes or b"")).hexdigest()
        return AITask.objects.create(
            prompt_name=self.prompt_name,
            provider=self.client.provider,
            model=self.client.model_name(image=self.image_bytes is not None),
            input_digest=digest[:16],
            input_preview=self.text[:PREVIEW_CHARS],
            has_image=self.image_bytes is not None,
            output=output[:MAX_OUTPUT_CHARS],
            status=status,
            error=_short(error) if error else "",
            attempts=max(self.attempts, 1),
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            latency_ms=int((time.monotonic() - self.started) * 1000),
        )


def parse_json(text: str):
    """Parse model output that should be JSON, tolerating ```json fences and chatter
    around a single top-level object."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start:end + 1])


def _short(exc) -> str:
    return str(exc).strip()[:500]
