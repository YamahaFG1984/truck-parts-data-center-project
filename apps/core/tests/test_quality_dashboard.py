from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalog.models import Part
from apps.catalog.services.quality import MISSING_LABELS, summary
from apps.catalog.tests.factories import CategoryFactory, PartFactory, PartNumberFactory

pytestmark = pytest.mark.django_db
DASHBOARD = reverse("core:quality")
PART_LIST = reverse("catalog:part_list")


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def user_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("ops", password="x"))
    return client


@pytest.fixture
def _seeded():
    """120 seeded parts inside the test transaction (rolled back afterwards)."""
    call_command("seed_demo", "--parts", "120", stdout=StringIO())


def test_anonymous_redirected(client):
    assert client.get(DASHBOARD).status_code == 302


def test_dashboard_shows_summary_numbers(user_client):
    PartFactory.create_batch(3, completeness_score=95)
    PartFactory(completeness_score=10, category=None)

    response = user_client.get(DASHBOARD)

    assert response.status_code == 200
    assert response.context["stats"]["total"] == 4
    assert response.context["stats"]["complete_share"] == 75
    body = response.content.decode()
    for label in MISSING_LABELS.values():
        assert label in body


def test_every_drill_down_count_matches_the_dashboard(user_client, _seeded):
    stats = summary()
    assert stats["total"] == 120

    for key, expected in stats["missing"].items():
        response = user_client.get(PART_LIST, {"missing": key})
        assert response.status_code == 200
        assert response.context["paginator"].count == expected, key

    for bucket in stats["distribution"]:
        response = user_client.get(PART_LIST, {"score": f"{bucket['low']}-{bucket['high']}"})
        assert response.context["paginator"].count == bucket["count"], bucket["label"]

    assert sum(b["count"] for b in stats["distribution"]) == stats["total"]


def test_dashboard_links_to_every_drill_down(user_client, _seeded):
    body = user_client.get(DASHBOARD).content.decode()

    for key in MISSING_LABELS:
        assert f"{PART_LIST}?missing={key}" in body
    for bucket in summary()["distribution"]:
        assert f"{PART_LIST}?score={bucket['low']}-{bucket['high']}" in body


def test_duplicate_groups_link_to_both_parts_in_admin(admin_client):
    a, b = PartFactory(sku="FIT-DUP-00001"), PartFactory(sku="FIT-DUP-00002")
    PartNumberFactory(part=a, number="20443906", kind="OE")
    PartNumberFactory(part=b, number="2044 3906", kind="OE")

    body = admin_client.get(DASHBOARD).content.decode()

    assert "20443906" in body
    for part in (a, b):
        assert reverse("admin:catalog_part_change", args=[part.pk]) in body
        assert reverse("catalog:part_detail", args=[part.sku]) in body


def test_dashboard_query_count_does_not_grow_with_data(user_client):
    def build(n):
        for i in range(n):
            part = PartFactory()
            PartNumberFactory(part=part, number=f"3000{i:04d}", kind="OE")
            PartNumberFactory(number=f"3000{i:04d}", kind="OE")  # duplicate group per i

    build(2)
    user_client.get(DASHBOARD)
    with CaptureQueriesContext(connection) as few:
        user_client.get(DASHBOARD)
    build(10)
    with CaptureQueriesContext(connection) as many:
        user_client.get(DASHBOARD)

    assert len(many) == len(few) <= 7


def test_part_list_filters_combine(user_client):
    category = CategoryFactory(name="刹车片")
    hit = PartFactory(category=category, status="draft", completeness_score=50)
    PartFactory(category=category, status="reviewed", completeness_score=50)
    PartFactory(category=category, status="draft", completeness_score=95)

    response = user_client.get(
        PART_LIST, {"status": "draft", "score": "40-70", "category": category.pk, "missing": "oe"}
    )

    assert list(response.context["parts"]) == [hit]
    labels = [label for _, label in response.context["filters"]]
    assert labels == ["缺 OE 号", "完整度 40–70", "草稿", "分类 刹车片"]


def test_part_list_ignores_unknown_filter_with_a_warning(user_client):
    PartFactory.create_batch(2)

    response = user_client.get(PART_LIST, {"missing": "colour"}, follow=True)

    assert response.context["paginator"].count == 2
    assert "未知的筛选项" in response.content.decode()


def test_part_list_query_count_does_not_grow_with_rows(user_client):
    PartFactory.create_batch(3, category=CategoryFactory(parent=CategoryFactory()))
    with CaptureQueriesContext(connection) as few:
        user_client.get(PART_LIST)
    PartFactory.create_batch(30, category=CategoryFactory(parent=CategoryFactory()))
    with CaptureQueriesContext(connection) as many:
        user_client.get(PART_LIST)

    assert len(many) == len(few)


def test_part_list_paginates_and_keeps_filters(user_client):
    PartFactory.create_batch(60, status="draft")

    page2 = user_client.get(PART_LIST, {"status": "draft", "page": 2})

    assert len(page2.context["parts"]) == 10
    assert "status=draft&amp;page=1" in page2.content.decode()
    assert Part.objects.count() == 60
