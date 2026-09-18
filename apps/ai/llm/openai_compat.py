"""Client for OpenAI-compatible chat APIs: DashScope (Qwen), DeepSeek, Moonshot (Kimi).

The only module in the project that imports openai. Text and vision can use
different endpoints, keys and models (DeepSeek has no vision model).
"""

import base64

import openai

from .base import BaseLLMClient, Completion

SYSTEM_PROMPT = "你是卡车配件数据助手。严格按用户要求的格式输出；需要 JSON 时只输出 JSON。"
RETRY_INSTRUCTION = "上一次的输出无法使用：{error}。请只输出符合要求格式的 JSON，不要任何解释。"


class OpenAICompatClient(BaseLLMClient):
    provider = "openai_compatible"
    api_errors = (openai.OpenAIError,)

    def __init__(self, *, base_url, api_key, model, vision_base_url, vision_api_key, vision_model,
                 timeout: float):
        self.model = model
        self.vision_model = vision_model
        self._text = openai.OpenAI(
            base_url=base_url or None, api_key=api_key, timeout=timeout, max_retries=2
        )
        vision_endpoint = (vision_base_url or base_url, vision_api_key or api_key)
        same_endpoint = vision_endpoint == (base_url, api_key)
        self._vision = self._text if same_endpoint else openai.OpenAI(
            base_url=vision_base_url or None, api_key=vision_api_key or api_key,
            timeout=timeout, max_retries=2,
        )

    def model_name(self, *, image: bool) -> str:
        return self.vision_model if image else self.model

    def _complete(self, *, prompt_name, prompt, temperature, image_bytes, want_json, history):
        content = prompt
        if image_bytes is not None:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _data_url(image_bytes)}},
            ]
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        for bad_output, error in history:
            messages += [
                {"role": "assistant", "content": bad_output},
                {"role": "user", "content": RETRY_INSTRUCTION.format(error=error)},
            ]
        kwargs = {"model": self.model_name(image=image_bytes is not None), "messages": messages,
                  "temperature": temperature}
        # Vision models on compatible endpoints often reject response_format; the
        # prompt already asks for JSON and base.parse_json tolerates fences.
        if want_json and image_bytes is None:
            kwargs["response_format"] = {"type": "json_object"}
        client = self._vision if image_bytes is not None else self._text
        response = client.chat.completions.create(**kwargs)
        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


def _data_url(image_bytes: bytes) -> str:
    mime = "image/jpeg"
    if image_bytes.startswith(b"\x89PNG"):
        mime = "image/png"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
