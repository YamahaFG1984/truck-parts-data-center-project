import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse

from apps.ai.llm.base import LLMError
from apps.ai.llm.mock import MockClient
from apps.ai.models import AISuggestion, AITask
from apps.ai.services.enrich import build_context, enrich_part
from apps.catalog.models import Part
from apps.catalog.tests.factories import (
    BRAKE_PAD_SCHEMA,
    CategoryFactory,
    FitmentFactory,
    PartFactory,
    PartNumberFactory,
)
from apps.suppliers.tests.factories import SupplierOfferFactory

pytestmark = pytest.mark.django_db
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def pads():
    return CategoryFactory(name="刹车片", attribute_schema=BRAKE_PAD_SCHEMA,
                           parent=CategoryFactory(name="制动系统"))


@pytest.fixture
def part(pads):
    part = PartFactory(sku="FIT-BPD-00001", name_en="Brake Pad Set", category=pads,
                       description_en="", keywords=[])
    PartNumberFactory(part=part, number="20443906", kind="OE")
    PartNumberFactory(part=part, number="K001234", kind="CROSS")
    FitmentFactory(part=part, make="Volvo", model="FH12")
    SupplierOfferFactory(part=part, unit_cost_usd=Decimal("17.90"))
    return part


def _suggestion(part, **payload_overrides):
    return enrich_part(Part.objects.get(pk=part.pk)) if not payload_overrides else (
        AISuggestion.objects.create(
            part=part, confidence=Decimal("0.8"),
            payload=enrich_part(part).payload | payload_overrides,
        )
    )


# --- context and generation ----------------------------------------------------------------------


def test_context_has_product_facts_and_reviewed_examples_but_no_prices(part, pads):
    PartFactory(category=pads, status="reviewed", description_en="Reviewed example text",
                completeness_score=90)
    PartFactory(category=pads, status="draft", description_en="Draft, not an example")

    context = build_context(part)

    assert context["oe_numbers"] == ["20443906"] and context["cross_numbers"] == ["K001234"]
    assert context["fitments"] == ["Volvo FH12 1993–2005"]
    assert context["category"] == "刹车片" and "刹车片" in context["category_options"]
    assert [e["description_en"] for e in context["examples"]] == ["Reviewed example text"]
    assert "17.90" not in str(context) and "Supplier" not in str(context)


def test_enrich_creates_pending_suggestion_and_reuses_it(part):
    first = enrich_part(part)
    again = enrich_part(part)

    assert first.pk == again.pk
    assert first.status == "pending" and first.payload["title_en"]
    assert first.ai_task.prompt_name == "enrich_part"
    assert AITask.objects.count() == 1  # the second call did not reach the model
    part.refresh_from_db()
    assert part.description_en == ""  # nothing written before review


# --- accept --------------------------------------------------------------------------------------


def test_accept_writes_chosen_fields_marks_source_and_rescored(part, admin_user):
    suggestion = enrich_part(part)

    applied = suggestion.accept(admin_user, ["title_en", "description_en", "keywords",
                                             "selling_points", "faq", "attributes"])

    part.refresh_from_db()
    assert applied == ["title_en", "description_en", "keywords", "selling_points", "faq",
                       "attributes"]
    assert part.title_en == suggestion.payload["title_en"]
    assert part.description_en.startswith("Heavy-duty brake pad set")
    assert len(part.selling_points) == 4 and part.faq[0]["q"]
    assert part.attributes["friction_material"] == "semi-metallic"
    assert part.source == "ai" and part.confidence == Decimal("0.78")
    assert f"[AI 补全 #{suggestion.pk}]" in part.notes and "admin" in part.notes
    assert part.completeness_score > 0
    suggestion.refresh_from_db()
    assert suggestion.status == "accepted" and suggestion.reviewed_by == admin_user


def test_accept_only_the_ticked_fields(part, admin_user):
    suggestion = enrich_part(part)

    suggestion.accept(admin_user, ["title_en"])

    part.refresh_from_db()
    assert part.title_en and part.description_en == "" and part.keywords == []
    assert suggestion.accepted_fields == ["title_en"]


def test_verified_part_keeps_its_values_but_blanks_are_filled(part, admin_user):
    Part.objects.filter(pk=part.pk).update(verified=True, description_en="Checked by a person")
    suggestion = enrich_part(Part.objects.get(pk=part.pk))

    rows = {r["key"]: r for r in suggestion.rows()}
    applied = suggestion.accept(admin_user, ["description_en", "title_en"])

    description = rows["description_en"]
    assert not description["applicable"] and "已人工确认" in description["why"]
    assert applied == ["title_en"]
    part.refresh_from_db()
    assert part.description_en == "Checked by a person" and part.title_en


def test_category_must_exist_in_the_tree(part, admin_user):
    Part.objects.filter(pk=part.pk).update(category=None)
    known = _suggestion(part, category="刹车片")
    unknown = AISuggestion.objects.create(part=part, payload=known.payload | {"category": "Rocket"})

    assert {r["key"]: r["applicable"] for r in unknown.rows()}["category"] is False
    known.accept(admin_user, ["category"])
    part.refresh_from_db()
    assert part.category.name == "刹车片"


def test_attributes_only_fill_missing_schema_keys_with_valid_values(part, admin_user):
    Part.objects.filter(pk=part.pk).update(attributes={"length_mm": 210})
    suggestion = _suggestion(part, attributes={
        "length_mm": 999,  # already set: never replaced
        "width_mm": 93,  # missing: filled
        "friction_material": "steel",  # not an allowed option: dropped
        "colour": "red",  # not in the schema: dropped
    })

    suggestion.accept(admin_user, ["attributes"])

    part.refresh_from_db()
    assert part.attributes == {"length_mm": 210, "width_mm": 93}


def test_cannot_review_twice(part, admin_user):
    suggestion = enrich_part(part)
    suggestion.accept(admin_user, ["title_en"])

    with pytest.raises(ValueError, match="审核过"):
        suggestion.reject(admin_user, "late")


# --- reject --------------------------------------------------------------------------------------


def test_reject_needs_a_reason_and_keeps_it(part, admin_user):
    suggestion = enrich_part(part)

    with pytest.raises(ValueError, match="拒绝原因"):
        suggestion.reject(admin_user, "  ")
    suggestion.reject(admin_user, "标题里的 OE 号写错了")

    suggestion.refresh_from_db()
    assert (suggestion.status, suggestion.reason) == ("rejected", "标题里的 OE 号写错了")
    part.refresh_from_db()
    assert part.title_en == "" and part.source != "ai"


# --- the only door -------------------------------------------------------------------------------


def test_only_accept_sets_a_part_source_to_ai():
    pattern = re.compile(r"source\s*=\s*(Source\.AI|[\"']ai[\"'])")
    hits = [
        str(path.relative_to(REPO))
        for path in (REPO / "apps").rglob("*.py")
        if "tests" not in path.parts and "migrations" not in path.parts
        and pattern.search(path.read_text())
    ]

    assert hits == ["apps/ai/models.py"]
    source = (REPO / "apps/ai/models.py").read_text()
    accept_body = source.split("def accept(", 1)[1].split("\n    def ", 1)[0]
    assert pattern.search(accept_body)
    assert len(pattern.findall(source)) == 1


# --- views ---------------------------------------------------------------------------------------


def test_enrich_button_returns_the_card_over_htmx(admin_client, part):
    response = admin_client.post(reverse("ai:enrich", args=[part.sku]), HTTP_HX_REQUEST="true")

    body = response.content.decode()
    assert response.status_code == 200 and "<html" not in body
    assert "采纳所选字段" in body and "上架标题" in body


def test_enrich_failure_shows_message_not_500(admin_client, part, monkeypatch):
    def boom(self, **kwargs):
        raise LLMError("timeout", task=None)

    monkeypatch.setattr(MockClient, "extract_json", boom)

    response = admin_client.post(reverse("ai:enrich", args=[part.sku]), HTTP_HX_REQUEST="true")

    assert response.status_code == 200 and "AI 补全失败" in response.content.decode()


def test_part_detail_shows_pending_suggestion(admin_client, part):
    enrich_part(part)

    body = admin_client.get(reverse("catalog:part_detail", args=[part.sku])).content.decode()

    assert "采纳所选字段" in body and 'hx-post="/ai/enrich/' not in body


def test_accept_and_reject_through_the_queue(admin_client, part, pads):
    other = PartFactory(category=pads)
    first, second = enrich_part(part), enrich_part(other)

    queue = admin_client.get(reverse("ai:review_queue"))
    accepted = admin_client.post(reverse("ai:accept", args=[first.pk]),
                                 {"fields": ["title_en", "keywords"]}, HTTP_HX_REQUEST="true")
    rejected = admin_client.post(reverse("ai:reject", args=[second.pk]), {"reason": "太泛了"},
                                 follow=True)

    assert len(queue.context["suggestions"]) == 2
    assert "已采纳 2 个字段" in accepted.content.decode()
    assert "原因已记录" in rejected.content.decode()
    assert len(admin_client.get(reverse("ai:review_queue")).context["suggestions"]) == 0
    history = admin_client.get(reverse("ai:review_queue"), {"status": "accepted"})
    assert [s.pk for s in history.context["suggestions"]] == [first.pk]


def test_reject_without_reason_shows_error(admin_client, part):
    suggestion = enrich_part(part)

    response = admin_client.post(reverse("ai:reject", args=[suggestion.pk]), {"reason": ""},
                                 HTTP_HX_REQUEST="true")

    assert "请写明拒绝原因" in response.content.decode()
    suggestion.refresh_from_db()
    assert suggestion.status == "pending"


def test_fields_that_would_replace_a_value_are_not_ticked_by_default(admin_client, part):
    Part.objects.filter(pk=part.pk).update(keywords=["old keyword"])
    suggestion = enrich_part(Part.objects.get(pk=part.pk))

    rows = {r["key"]: r for r in suggestion.rows()}
    body = admin_client.get(reverse("ai:review_queue")).content.decode()

    assert rows["keywords"]["replaces"] and "会覆盖当前值" in rows["keywords"]["why"]
    assert not rows["title_en"]["replaces"]
    assert 'value="title_en" checked' in body
    assert 'value="keywords" checked' not in body and 'value="category" checked' not in body
