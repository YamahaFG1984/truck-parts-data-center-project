import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalog.models import Part

from .factories import (
    BrandFactory,
    CategoryFactory,
    FitmentFactory,
    PartFactory,
    PartImageFactory,
    PartNumberFactory,
)

pytestmark = pytest.mark.django_db


def _full_part(**kwargs):
    part = PartFactory(**kwargs)
    PartNumberFactory(part=part)
    FitmentFactory(part=part)
    PartImageFactory(part=part)
    return part


@pytest.mark.parametrize("model", ["part", "partnumber", "category", "brand"])
def test_changelist_loads(admin_client, model):
    _full_part()

    response = admin_client.get(reverse(f"admin:catalog_{model}_changelist"))

    assert response.status_code == 200


def test_part_change_page_shows_inlines(admin_client):
    part = _full_part()

    response = admin_client.get(reverse("admin:catalog_part_change", args=[part.pk]))

    assert response.status_code == 200
    body = response.content.decode()
    assert "numbers-TOTAL_FORMS" in body
    assert "fitments-TOTAL_FORMS" in body
    assert "images-TOTAL_FORMS" in body


@pytest.mark.parametrize("model", ["part", "partnumber", "category", "brand"])
def test_add_page_loads(admin_client, model):
    response = admin_client.get(reverse(f"admin:catalog_{model}_add"))

    assert response.status_code == 200


@pytest.mark.parametrize("term", ["2044-3906", "20 443 906", "20443906", "443906"])
def test_part_search_matches_normalized_number(admin_client, term):
    target = PartFactory()
    PartNumberFactory(part=target, number="20443906")
    PartNumberFactory(number="99999999")  # another part that must not match

    response = admin_client.get(reverse("admin:catalog_part_changelist"), {"q": term})

    assert list(response.context["cl"].result_list) == [target]


def test_partnumber_search_matches_normalized_number(admin_client):
    pn = PartNumberFactory(number="A 000 420 15 20")

    response = admin_client.get(
        reverse("admin:catalog_partnumber_changelist"), {"q": "a0004201520"}
    )

    assert list(response.context["cl"].result_list) == [pn]


def test_part_changelist_query_count_does_not_grow_with_rows(admin_client):
    url = reverse("admin:catalog_part_changelist")
    for _ in range(2):
        _full_part()
    admin_client.get(url)  # warm up session / content types

    with CaptureQueriesContext(connection) as few:
        admin_client.get(url)
    for _ in range(8):
        _full_part()
    with CaptureQueriesContext(connection) as many:
        admin_client.get(url)

    assert len(many) == len(few)


def test_category_changelist_counts_parts_without_extra_queries(admin_client):
    category = CategoryFactory()
    PartFactory.create_batch(3, category=category)

    response = admin_client.get(reverse("admin:catalog_category_changelist"))

    row = next(r for r in response.context["cl"].result_list if r.pk == category.pk)
    assert row._part_count == 3


def test_ticking_verified_stamps_user_and_time(admin_client, admin_user):
    part = PartFactory()
    url = reverse("admin:catalog_part_change", args=[part.pk])
    data = {
        "sku": part.sku,
        "name_en": part.name_en,
        "name_zh": "",
        "category": part.category_id,
        "status": "reviewed",
        "attributes": "{}",
        "packaging": "{}",
        "keywords": "[]",
        "description_en": "",
        "notes": "",
        "source": "manual",
        "confidence": "1.00",
        "verified": "on",
    }
    for prefix in ["numbers", "fitments", "images"]:
        data |= {
            f"{prefix}-TOTAL_FORMS": "0",
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
        }

    response = admin_client.post(url, data)

    assert response.status_code == 302, response.context["adminform"].form.errors
    part.refresh_from_db()
    assert part.status == Part.Status.REVIEWED
    assert part.verified_by == admin_user
    assert part.verified_at is not None


@pytest.mark.parametrize(
    ("model", "field"), [("part", "category"), ("partnumber", "brand")]
)
def test_autocomplete_endpoints(admin_client, model, field):
    CategoryFactory(name="刹车片")
    BrandFactory(name="Volvo")

    response = admin_client.get(
        reverse("admin:autocomplete"),
        {"app_label": "catalog", "model_name": model, "field_name": field, "term": ""},
    )

    assert response.status_code == 200
    assert response.json()["results"]
