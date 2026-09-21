import pytest

from apps.ai.llm.base import LLMError
from apps.ai.llm.mock import MockClient
from apps.sources.models import MappingTemplate
from apps.sources.services import mapping

from .workbooks import HEADERS_A, HEADERS_B

pytestmark = pytest.mark.django_db
EXPECTED = ["record_id", "supplier_sku", "name", "fitment", "position", "oe_numbers", "dims",
            "price", "currency", "moq", "quote_date"]


@pytest.mark.parametrize("headers", [HEADERS_A, HEADERS_B])
def test_two_suppliers_with_no_header_in_common_map_to_the_same_fields(headers, supplier):
    columns = mapping.suggest(headers, [], supplier)

    assert [c["field"] for c in columns] == EXPECTED
    assert {c["source"] for c in columns} == {"synonym"}


@pytest.mark.parametrize(("header", "field", "confidence"), [
    ("Brand Number", "supplier_sku", 1.0),  # the supplier's own number, not a brand name
    ("Brand", "brand", 1.0),
    ("Part #", "supplier_sku", 1.0),
    ("Unit Price (EUR)", "price", 0.9),
    ("OE/Reference", "oe_numbers", 1.0),
])
def test_synonym_edge_cases(header, field, confidence):
    assert mapping.match_synonym(header) == (field, confidence)


def test_unrecognised_headers_go_to_the_model_with_three_sample_rows_only(supplier, monkeypatch):
    seen = {}
    real = MockClient.extract_json

    def spy(self, **kwargs):
        seen.update(kwargs["variables"])
        return real(self, **kwargs)

    monkeypatch.setattr(MockClient, "extract_json", spy)
    rows = [{"Part No.": f"P-{i}", "Vendor Item": f"V-{i}", "Cab Style": "Day"} for i in range(9)]

    columns = mapping.suggest(["Part No.", "Vendor Item", "Cab Style"], rows, supplier)

    assert [(c["field"], c["source"]) for c in columns] == [
        ("supplier_sku", "synonym"), ("supplier_sku", "ai"), ("spec", "ai")]
    assert seen["headers"] == ["Vendor Item", "Cab Style"]  # only what synonyms missed
    assert seen["sample_rows"] == [{"Vendor Item": f"V-{i}", "Cab Style": "Day"} for i in range(3)]


def test_a_model_failure_leaves_the_column_for_a_person(supplier, monkeypatch):
    def down(self, **kwargs):
        raise LLMError("timeout", task=None)

    monkeypatch.setattr(MockClient, "extract_json", down)

    [column] = mapping.suggest(["Cab Style"], [], supplier)

    assert (column["field"], column["source"]) == ("ignore", "none")
    assert "AI 调用失败" in column["reason"]


def test_a_confirmed_template_is_reused_even_when_columns_move(supplier, django_user_model):
    user = django_user_model.objects.create_user("ops", password="x")
    columns = mapping.suggest(HEADERS_A, [], supplier)
    columns[4]["field"] = "note"  # a person changed one column
    mapping.save_template(supplier, HEADERS_A, columns, user)

    reordered = list(reversed(HEADERS_A))
    again = mapping.suggest(reordered, [], supplier)

    assert {c["source"] for c in again} == {"template"}
    assert {c["header"]: c["field"] for c in again}["Position"] == "note"
    assert MappingTemplate.objects.count() == 1


@pytest.mark.parametrize(("fields", "error"), [
    (["price", "price", "name"], "单价"),
    (["price", "currency", "moq"], "至少要有一列能识别产品"),
])
def test_invalid_mappings_are_refused(fields, error):
    columns = [{"header": f"H{i}", "field": f} for i, f in enumerate(fields)]

    errors, _ = mapping.validate(columns)

    assert any(error in e for e in errors)


def test_several_oe_columns_are_allowed_and_a_missing_identity_is_a_warning():
    columns = [{"header": "OE", "field": "oe_numbers"}, {"header": "Cross", "field": "oe_numbers"},
               {"header": "Desc", "field": "name"}]

    errors, warnings = mapping.validate(columns)

    assert errors == [] and "无法识别哪条是更新" in warnings[0]
