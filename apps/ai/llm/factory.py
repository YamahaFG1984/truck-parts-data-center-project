"""The single entry point business code uses to get an LLM client."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseLLMClient


def get_client() -> BaseLLMClient:
    provider = settings.LLM_PROVIDER
    if provider == "mock":
        from .mock import MockClient

        return MockClient()
    if provider == "openai_compatible":
        if not settings.LLM_API_KEY:
            raise ImproperlyConfigured(
                "LLM_PROVIDER=openai_compatible 但 LLM_API_KEY 为空。"
                "填写密钥，或在演示时设置 LLM_PROVIDER=mock。"
            )
        from .openai_compat import OpenAICompatClient

        return OpenAICompatClient(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            vision_base_url=settings.LLM_VISION_BASE_URL,
            vision_api_key=settings.LLM_VISION_API_KEY,
            vision_model=settings.LLM_VISION_MODEL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
    raise ImproperlyConfigured(f"未知的 LLM_PROVIDER：{provider!r}（可选 mock、openai_compatible）")
