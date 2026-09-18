import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ai.llm.base import LLMError
from apps.ai.llm.mock import MockClient
from apps.ai.models import AITask
from apps.ai.schemas import MappingItem, MappingResult
from apps.importer.models import ImportBatch
from apps.importer.services import mapping
from apps.importer.services.mapping import FIELD_LABELS, match_synonym, suggest_mapping

from .test_loader_and_upload import XLSX, _xlsx_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


class SpyClient:
    """Records extract_json calls and answers with a scripted MappingResult."""

    def __init__(self, answer=None, error=None):
        self.calls, self.answer, self.error = [], answer, error

    def extract_json(self, *, prompt_name, variables, schema):
        self.calls.append(variables)
        if self.error:
            raise LLMError("boom", task=None)
        return MappingResult(mapping=self.answer or []), None


@pytest.mark.parametrize(
    ("header", "field", "confidence"),
    [("Part No.", "supplier_pn", 1.0), ("OEM NO", "oe_number", 1.0), ("OE号", "oe_number", 1.0),
     ("Ref", "cross_number", 1.0), ("适用车型", "make", 1.0), ("FOB Price(USD)", "unit_cost", 0.9),
     ("Weight(KG)", "gross_weight_kg", 0.9), ("Lead Time (days)", "lead_days", 0.9),
     ("Qty/Ctn", "pcs_per_carton", 1.0), ("箱规", "carton_l_cm", 1.0), ("Model", "model", 1.0)],
)
def test_synonyms(header, field, confidence):
    assert match_synonym(header) == (field, confidence)


@pytest.mark.parametrize("header", ["Price Term", "Colour", "", "   "])
def test_unknown_headers(header):
    assert match_synonym(header) is None


def test_every_label_covers_a_standard_field():
    assert "ignore" in FIELD_LABELS and len(FIELD_LABELS) == len(mapping.STANDARD_FIELDS)


def test_known_headers_never_call_the_llm():
    spy = SpyClient()

    result = suggest_mapping(["Part No.", "OEM NO", "FOB Price(USD)"], [], client=spy)

    assert spy.calls == []
    assert [r["source"] for r in result] == ["synonym"] * 3


def test_only_unknown_headers_go_to_the_llm_once():
    spy = SpyClient(answer=[
        MappingItem(header="Colour", field="description_en", confidence=0.4, reason="颜色写入备注"),
        MappingItem(header="OEM NO", field="ignore", confidence=1, reason="should be ignored"),
    ])
    rows = [{"OEM NO": "20443906", "Colour": "black", "Price Term": "FOB"}] * 5

    result = suggest_mapping(["OEM NO", "Colour", "Price Term"], rows, client=spy)

    assert len(spy.calls) == 1
    assert spy.calls[0]["headers"] == ["Colour", "Price Term"]
    assert spy.calls[0]["sample_rows"] == [{"Colour": "black", "Price Term": "FOB"}] * 3
    by_header = {r["header"]: r for r in result}
    assert by_header["OEM NO"]["field"] == "oe_number"  # the LLM's answer for it was ignored
    colour, term = by_header["Colour"], by_header["Price Term"]
    assert (colour["source"], colour["field"]) == ("ai", "description_en")
    assert (term["source"], term["field"]) == ("none", "ignore")


def test_llm_failure_leaves_unknown_columns_ignored_with_reason():
    result = suggest_mapping(["Colour"], [], client=SpyClient(error=True))

    assert result == [{"header": "Colour", "field": "ignore", "source": "none",
                       "confidence": 0.0, "reason": "AI 调用失败：boom"}]


def test_default_client_is_the_configured_one_and_is_audited():
    suggest_mapping(["Colour"], [{"Colour": "black"}])  # settings: mock provider

    assert AITask.objects.filter(prompt_name="column_mapping", status="ok").count() == 1


# --- mapping page ----------------------------------------------------------------------------


@pytest.fixture
def batch(admin_client):
    data = _xlsx_bytes([["Part No.", "OEM NO", "Colour"], ["HB-1", "20443906", "black"]])
    admin_client.post(reverse("importer:upload"),
                      {"file": SimpleUploadedFile("q.xlsx", data, content_type=XLSX)})
    return ImportBatch.objects.get()


def test_mapping_page_suggests_once_and_stores_it(admin_client, batch, monkeypatch):
    calls = []
    real = MockClient.extract_json

    def counting(self, **kwargs):
        calls.append(kwargs["variables"]["headers"])
        return real(self, **kwargs)

    monkeypatch.setattr(MockClient, "extract_json", counting)
    url = reverse("importer:mapping", args=[batch.pk])

    first = admin_client.get(url)
    admin_client.get(url)

    assert first.status_code == 200
    assert calls == [["Colour"]]  # synonyms handled the rest; reload did not ask again
    batch.refresh_from_db()
    assert [c["field"] for c in batch.column_mapping["columns"]][:2] == ["supplier_pn", "oe_number"]
    assert "同义词" in first.content.decode()


def test_saving_mapping_records_manual_changes_and_options(admin_client, batch):
    url = reverse("importer:mapping", args=[batch.pk])
    admin_client.get(url)

    response = admin_client.post(url, {"field_0": "supplier_pn", "field_1": "cross_number",
                                       "field_2": "ignore", "overwrite": "on"})

    assert response.status_code == 302
    batch.refresh_from_db()
    columns = batch.column_mapping["columns"]
    assert columns[0]["source"] == "synonym"
    assert (columns[1]["field"], columns[1]["source"], columns[1]["confidence"]) == (
        "cross_number", "manual", 1.0)
    assert batch.column_mapping["overwrite"] is True
    assert batch.status == "mapped"


def test_invalid_field_is_rejected(admin_client, batch):
    url = reverse("importer:mapping", args=[batch.pk])
    admin_client.get(url)

    response = admin_client.post(url, {"field_0": "colour"}, follow=True)

    assert "目标字段无效" in response.content.decode()
    batch.refresh_from_db()
    assert batch.status == "uploaded"


def test_reset_recomputes_suggestions(admin_client, batch):
    url = reverse("importer:mapping", args=[batch.pk])
    admin_client.get(url)
    admin_client.post(url, {"field_0": "ignore", "field_1": "ignore", "field_2": "ignore"})

    admin_client.post(url, {"reset": "1"})
    admin_client.get(url)

    batch.refresh_from_db()
    assert batch.column_mapping["columns"][1]["field"] == "oe_number"
    assert batch.status == "uploaded"
