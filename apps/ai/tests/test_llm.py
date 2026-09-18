import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from apps.ai.llm.base import LLMError, parse_json
from apps.ai.llm.factory import get_client
from apps.ai.llm.mock import MockClient
from apps.ai.llm.openai_compat import OpenAICompatClient
from apps.ai.models import AITask
from apps.ai.prompts.loader import PROMPT_DIR, load_prompt
from apps.ai.schemas import EnrichResult, ExtractResult, ImageFinding, MappingResult

pytestmark = pytest.mark.django_db
REPO = Path(__file__).resolve().parents[3]

VARIABLES = {
    "column_mapping": {"sku_prefix": "FIT-", "headers": ["Part No.", "OEM NO"],
                       "sample_rows": [{"Part No.": "HB-1", "OEM NO": "20443906"}]},
    "extract_fields": {"text": "Brake pad for Volvo FH12, OE 20443906"},
    "enrich_part": {"sku": "FIT-BPD-00001", "name_en": "Brake Pad Set", "name_zh": "刹车片",
                    "category": "刹车片", "category_options": ["刹车片", "刹车盘"],
                    "attribute_schema": {"fields": []}, "oe_numbers": ["20443906"],
                    "cross_numbers": [], "fitments": ["Volvo FH12"], "attributes": {},
                    "examples": []},
    "image_identify": {},
}
SCHEMAS = {"column_mapping": MappingResult, "extract_fields": ExtractResult,
           "enrich_part": EnrichResult, "image_identify": ImageFinding}


# --- prompts ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(SCHEMAS))
def test_every_prompt_renders_and_forbids_invented_numbers(name):
    prompt = load_prompt(name)

    text = prompt.render(VARIABLES[name])

    assert "不要编造编号" in text
    assert "{" in text and "{{" not in text  # JSON braces survive formatting, once
    assert prompt.description


def test_missing_variable_raises_key_error_naming_it():
    with pytest.raises(KeyError, match="sample_rows"):
        load_prompt("column_mapping").render({"sku_prefix": "FIT-", "headers": []})


def test_front_matter_and_json_rendering_of_variables():
    prompt = load_prompt("enrich_part")

    text = prompt.render(VARIABLES["enrich_part"])

    assert prompt.temperature == 0.4
    assert 'OE 号: ["20443906"]' in text  # lists rendered as JSON, Chinese kept readable


def test_every_prompt_has_a_valid_mock_example():
    for name, schema in SCHEMAS.items():
        schema.model_validate(json.loads((PROMPT_DIR / f"{name}.example.json").read_text()))


# --- mock client --------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["column_mapping", "extract_fields", "enrich_part"])
def test_mock_extract_json_returns_validated_object_and_audit_row(name):
    result, task = MockClient().extract_json(
        prompt_name=name, variables=VARIABLES[name], schema=SCHEMAS[name]
    )

    assert isinstance(result, SCHEMAS[name])
    assert (task.status, task.provider, task.model, task.attempts) == ("ok", "mock", "mock", 1)
    assert AITask.objects.count() == 1


def test_mock_describe_image():
    finding, task = MockClient().describe_image(
        prompt_name="image_identify", image_bytes=b"\xff\xd8fake", schema=ImageFinding
    )

    assert finding.visible_numbers == ["26570367"]
    assert task.has_image and task.status == "ok"


def test_factory_returns_mock_by_default_in_tests():
    assert isinstance(get_client(), MockClient)


def test_factory_requires_a_key_for_real_provider(settings):
    settings.LLM_PROVIDER = "openai_compatible"
    settings.LLM_API_KEY = ""

    with pytest.raises(ImproperlyConfigured, match="LLM_API_KEY"):
        get_client()


def test_factory_rejects_unknown_provider(settings):
    settings.LLM_PROVIDER = "magic"

    with pytest.raises(ImproperlyConfigured):
        get_client()


def test_factory_builds_openai_client_with_separate_vision_endpoint(settings):
    settings.LLM_PROVIDER = "openai_compatible"
    settings.LLM_API_KEY = "sk-text"
    settings.LLM_BASE_URL = "https://api.deepseek.com"
    settings.LLM_MODEL = "deepseek-chat"
    settings.LLM_VISION_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    settings.LLM_VISION_API_KEY = "sk-vision"
    settings.LLM_VISION_MODEL = "qwen-vl-plus"

    client = get_client()

    assert isinstance(client, OpenAICompatClient)
    assert client._vision is not client._text
    assert client.model_name(image=True) == "qwen-vl-plus"


# --- OpenAI-compatible client against a fake API --------------------------------------------------


class FakeAPI:
    """Stands in for openai.OpenAI().chat.completions; replies from a script."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


def _client(api: FakeAPI) -> OpenAICompatClient:
    client = OpenAICompatClient(base_url="https://x", api_key="k", model="qwen-plus",
                                vision_base_url="", vision_api_key="", vision_model="qwen-vl-plus",
                                timeout=5)
    client._text = client._vision = api
    return client


GOOD = json.dumps({"part_type": "brake pad", "visible_numbers": ["20443906"], "confidence": 0.8})


def test_openai_success_uses_json_mode_and_records_tokens():
    api = FakeAPI(json.dumps({"mapping": []}))

    result, task = _client(api).extract_json(
        prompt_name="column_mapping", variables=VARIABLES["column_mapping"], schema=MappingResult
    )

    assert result.mapping == []
    assert api.calls[0]["response_format"] == {"type": "json_object"}
    assert api.calls[0]["model"] == "qwen-plus" and api.calls[0]["temperature"] == 0
    assert (task.status, task.attempts, task.prompt_tokens, task.completion_tokens) == (
        "ok", 1, 100, 20)


def test_broken_json_is_retried_with_the_error_fed_back():
    api = FakeAPI("Sure! Here you go: {not json", f"```json\n{GOOD}\n```")

    finding, task = _client(api).describe_image(
        prompt_name="image_identify", image_bytes=b"\x89PNGxxxx", schema=ImageFinding
    )

    assert finding.visible_numbers == ["20443906"]
    assert (task.status, task.attempts, task.prompt_tokens) == ("ok", 2, 200)
    retry_messages = api.calls[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": "Sure! Here you go: {not json"}
    assert "无法使用" in retry_messages[-1]["content"]


def test_schema_violation_counts_as_bad_output():
    wrong_field = json.dumps({"mapping": [{"header": "X", "field": "colour", "confidence": 1}]})
    api = FakeAPI(wrong_field, wrong_field)

    with pytest.raises(LLMError) as exc:
        _client(api).extract_json(
            prompt_name="column_mapping", variables=VARIABLES["column_mapping"],
            schema=MappingResult,
        )

    task = exc.value.task
    assert (task.status, task.attempts) == ("invalid_json", 2)
    assert "colour" in task.error and task.output == wrong_field
    assert AITask.objects.count() == 1


def test_timeout_is_recorded_as_error():
    request = httpx.Request("POST", "https://x/chat/completions")
    api = FakeAPI(openai.APITimeoutError(request=request))

    with pytest.raises(LLMError, match="模型调用失败") as exc:
        _client(api).extract_json(
            prompt_name="extract_fields", variables=VARIABLES["extract_fields"],
            schema=ExtractResult,
        )

    assert exc.value.task.status == "error"
    assert "timed out" in exc.value.task.error.lower()


def test_image_request_sends_data_url_without_json_mode():
    api = FakeAPI(GOOD)

    _client(api).describe_image(prompt_name="image_identify", image_bytes=b"\x89PNGxxxx",
                                schema=ImageFinding)

    call = api.calls[0]
    assert call["model"] == "qwen-vl-plus"
    assert "response_format" not in call
    image_part = call["messages"][1]["content"][1]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_generate_text_has_no_json_mode():
    api = FakeAPI("plain text answer")

    text, task = _client(api).generate_text(
        prompt_name="extract_fields", variables=VARIABLES["extract_fields"]
    )

    assert text == "plain text answer" and task.status == "ok"
    assert "response_format" not in api.calls[0]


# --- audit trail ----------------------------------------------------------------------------------


def test_audit_row_keeps_only_digest_and_short_preview():
    long_text = "Brake pad catalog line. " * 200
    MockClient().extract_json(prompt_name="extract_fields", variables={"text": long_text},
                              schema=ExtractResult)

    task = AITask.objects.get()
    assert len(task.input_digest) == 16
    assert len(task.input_preview) == 500
    assert long_text not in task.input_preview


@pytest.mark.parametrize(
    ("text", "expected"),
    [('{"a": 1}', {"a": 1}), ('```json\n{"a": 1}\n```', {"a": 1}),
     ('Here it is: {"a": {"b": 2}} hope that helps', {"a": {"b": 2}})],
)
def test_parse_json_tolerates_fences_and_chatter(text, expected):
    assert parse_json(text) == expected


def test_parse_json_rejects_non_json():
    with pytest.raises(ValueError):
        parse_json("no braces here")


def test_only_the_openai_client_module_imports_openai():
    offenders = [
        str(path.relative_to(REPO))
        for path in (REPO / "apps").rglob("*.py")
        if re.search(r"^\s*(import openai|from openai)", path.read_text(), re.MULTILINE)
        and path.name not in {"openai_compat.py", "test_llm.py"}
    ]

    assert offenders == []


def test_admin_is_read_only(admin_client):
    MockClient().extract_json(prompt_name="extract_fields", variables=VARIABLES["extract_fields"],
                              schema=ExtractResult)

    assert admin_client.get(reverse("admin:ai_aitask_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:ai_aitask_add")).status_code == 403
