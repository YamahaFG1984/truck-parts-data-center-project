from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalog.models import Part
from apps.catalog.services import quality
from apps.catalog.services.quality import WEIGHTS, duplicates, evaluate, recompute, summary
from apps.suppliers.tests.factories import SupplierOfferFactory

from .factories import (
    BRAKE_PAD_SCHEMA,
    CategoryFactory,
    FitmentFactory,
    PartFactory,
    PartImageFactory,
    PartNumberFactory,
)

pytestmark = pytest.mark.django_db
FULL_PACKAGING = {"unit": "set", "pcs_per_carton": 20, "gross_weight_kg": 12.5}


def complete_part(**overrides):
    """A part that has everything the score looks at."""
    fields = {
        "name_en": "Brake Pad Set",
        "category": CategoryFactory(attribute_schema=BRAKE_PAD_SCHEMA),
        "attributes": {"length_mm": 210, "width_mm": 93},
        "packaging": FULL_PACKAGING,
    } | overrides
    part = PartFactory(**fields)
    PartNumberFactory(part=part, kind="OE")
    PartNumberFactory(part=part, kind="CROSS")
    FitmentFactory(part=part)
    PartImageFactory(part=part)
    SupplierOfferFactory(part=part)
    return part


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_complete_part_scores_100():
    assert evaluate(complete_part()) == quality.QualityReport(score=100, missing=[])


def _remove(part, item):
    removals = {
        "name": lambda: Part.objects.filter(pk=part.pk).update(name_en="Pad"),  # < 5 chars
        "category": lambda: Part.objects.filter(pk=part.pk).update(category=None),
        "oe": lambda: part.numbers.filter(kind="OE").delete(),
        "cross": lambda: part.numbers.filter(kind="CROSS").delete(),
        "fitment": lambda: part.fitments.all().delete(),
        "image": lambda: part.images.update(is_primary=False),  # only a primary image counts
        "attributes": lambda: Part.objects.filter(pk=part.pk).update(attributes={"length_mm": 210}),
        "packaging": lambda: Part.objects.filter(pk=part.pk).update(packaging={"unit": "set"}),
        "offer": lambda: part.offers.all().delete(),
    }
    removals[item]()


@pytest.mark.parametrize("item", list(WEIGHTS))
def test_each_missing_item_costs_its_weight(item):
    part = complete_part()
    _remove(part, item)

    report = evaluate(Part.objects.get(pk=part.pk))

    # Without a category there is no schema to check specs against, so the
    # attributes item is lost as well: unknown is not the same as complete.
    expected = [item, "attributes"] if item == "category" else [item]
    assert report.missing == [m for m in WEIGHTS if m in expected]
    assert report.score == 100 - sum(WEIGHTS[m] for m in expected)


def test_category_without_required_attributes_gets_attribute_points():
    part = complete_part(category=CategoryFactory(attribute_schema={"fields": []}), attributes={})

    assert "attributes" not in evaluate(part).missing


def test_bare_part_scores_zero():
    part = PartFactory(name_en="", category=None)

    assert evaluate(part).score == 0


def test_recompute_writes_scores_and_reports_changes():
    good, bare = complete_part(), PartFactory(name_en="", category=None, completeness_score=55)

    assert recompute() == 2
    good.refresh_from_db()
    bare.refresh_from_db()
    assert (good.completeness_score, bare.completeness_score) == (100, 0)
    assert recompute() == 0  # nothing changed the second time


def test_recompute_only_touches_given_parts():
    a, b = complete_part(), complete_part()

    recompute(Part.objects.filter(pk=a.pk))

    assert Part.objects.get(pk=a.pk).completeness_score == 100
    assert Part.objects.get(pk=b.pk).completeness_score == 0


def test_recompute_query_count_does_not_grow_with_parts():
    for _ in range(5):
        complete_part()
    with CaptureQueriesContext(connection) as few:
        recompute()

    Part.objects.update(completeness_score=0)
    for _ in range(25):
        complete_part()
    Part.objects.update(completeness_score=0)
    with CaptureQueriesContext(connection) as many:
        recompute()

    assert len(many) == len(few)
    assert not any(q["sql"].lstrip().upper().startswith("INSERT") for q in many.captured_queries)


def test_recompute_command():
    complete_part()
    out = StringIO()

    call_command("recompute_quality", stdout=out)

    assert "recomputed 1 parts (1 scores changed)" in out.getvalue()


@pytest.mark.parametrize(
    ("score", "bucket"), [(0, "0–39"), (39, "0–39"), (40, "40–69"), (69, "40–69"),
                          (70, "70–89"), (89, "70–89"), (90, "90–100"), (100, "90–100")],
)
def test_summary_bucket_boundaries(score, bucket):
    PartFactory(completeness_score=score)

    counts = {b["label"]: b["count"] for b in summary()["distribution"]}

    assert counts[bucket] == 1 and sum(counts.values()) == 1


def test_summary_counts_missing_items_in_fixed_queries(django_assert_num_queries):
    complete_part()
    PartFactory(name_en="", category=None)

    with django_assert_num_queries(2):  # one aggregate + duplicate groups
        result = summary()

    assert result["total"] == 2
    assert result["missing"]["oe"] == 1 and result["missing"]["offer"] == 1
    assert result["missing"]["category"] == 1


def test_duplicates_groups_parts_sharing_a_number():
    a, b, c = PartFactory(sku="FIT-A"), PartFactory(sku="FIT-B"), PartFactory(sku="FIT-C")
    PartNumberFactory(part=a, number="20443906", kind="OE")
    PartNumberFactory(part=b, number="2044-3906", kind="OE")
    PartNumberFactory(part=c, number="20443906", kind="SUPPLIER")  # supplier numbers ignored
    PartNumberFactory(part=c, number="99999999", kind="OE")  # unique, not a duplicate

    groups = duplicates()

    assert [(norm, [p.sku for p in parts]) for norm, parts in groups] == [
        ("20443906", ["FIT-A", "FIT-B"])
    ]
    assert summary()["duplicate_groups"] == 1


def test_seed_demo_scores_parts_and_has_ten_duplicate_groups():
    call_command("seed_demo", stdout=StringIO())

    assert Part.objects.filter(completeness_score=0).count() == 0  # every seeded part scored
    assert len(duplicates()) == 10


def test_saving_a_part_in_admin_rescores_it(admin_client):
    part = complete_part()
    Part.objects.filter(pk=part.pk).update(completeness_score=0)
    data = {
        "sku": part.sku, "name_en": part.name_en, "name_zh": "", "category": part.category_id,
        "status": "draft", "attributes": '{"length_mm": 210, "width_mm": 93}',
        "packaging": '{"unit": "set", "pcs_per_carton": 20, "gross_weight_kg": 12.5}',
        "keywords": "[]", "description_en": "", "notes": "", "source": "manual",
        "confidence": "1.00",
    }
    for prefix in ["numbers", "fitments", "images"]:
        data |= {f"{prefix}-TOTAL_FORMS": "0", f"{prefix}-INITIAL_FORMS": "0",
                 f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"}

    response = admin_client.post(reverse("admin:catalog_part_change", args=[part.pk]), data)

    assert response.status_code == 302
    assert Part.objects.get(pk=part.pk).completeness_score == 100
