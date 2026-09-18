"""Offline client: returns prompts/<name>.example.json after a short, configurable
delay. Lets every page work without network or API key (PRD non-functional)."""

import time

from django.conf import settings

from ..prompts.loader import example_output
from .base import BaseLLMClient, Completion


class MockClient(BaseLLMClient):
    provider = "mock"

    def model_name(self, *, image: bool) -> str:
        return "mock"

    def _complete(self, *, prompt_name, prompt, temperature, image_bytes, want_json, history):
        time.sleep(settings.LLM_MOCK_LATENCY_SECONDS)
        text = example_output(prompt_name)
        # Rough token estimate so the audit trail and cost figures look plausible.
        return Completion(text, prompt_tokens=len(prompt) // 3, completion_tokens=len(text) // 3)
