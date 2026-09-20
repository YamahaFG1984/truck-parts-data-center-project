import pytest
from django.urls import reverse

from apps.ai.models import AISuggestion, AITask
from apps.catalog.models import Part
from apps.catalog.tests.factories import PartFactory, PartNumberFactory
from apps.inquiries.models import Inquiry

pytestmark = pytest.mark.django_db
HOME = reverse("core:home")


@pytest.fixture
def sales(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("sales", password="x"))
    return client


def suggestion(part, status=AISuggestion.Status.PENDING):
    task = AITask.objects.create(prompt_name="part_enrich", provider="mock", model="mock",
                                 input_digest="0" * 16, status=AITask.Status.OK)
    return AISuggestion.objects.create(part=part, ai_task=task, status=status,
                                       payload={"title_en": "Brake Pad Set"})


def test_home_redirects_anonymous_user_to_login(client):
    response = client.get(HOME)

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_home_shows_the_search_box_and_the_other_entry_points(sales):
    body = sales.get(HOME).content.decode()

    assert f'action="{reverse("catalog:search")}"' in body and 'name="q"' in body
    for url in (reverse("inquiries:image"), reverse("importer:upload"),
                reverse("core:quality"), reverse("ai:review_queue")):
        assert url in body


def test_home_numbers_match_the_data(sales):
    complete = PartFactory(status=Part.Status.PUBLISHED, completeness_score=95)
    PartNumberFactory(part=complete, number="20443906", kind="OE")
    twin = PartFactory(completeness_score=31)
    PartNumberFactory(part=twin, number="2044-3906", kind="OE")  # same number: a duplicate group
    suggestion(complete)
    suggestion(twin, status=AISuggestion.Status.ACCEPTED)  # history, not pending

    context = sales.get(HOME).context

    assert context["stats"]["total"] == 2
    assert context["stats"]["average"] == 63  # (95 + 31) / 2
    assert context["stats"]["duplicate_groups"] == 1
    assert context["pending"] == 1


def test_home_lists_the_most_missing_items_first_with_drill_down_links(sales):
    for _ in range(3):
        PartFactory(category=None)

    response = sales.get(HOME)

    top = response.context["top_missing"]
    assert [m["count"] for m in top] == sorted((m["count"] for m in top), reverse=True)
    assert top[0]["percent"] == 100
    link = f'{reverse("catalog:part_list")}?missing={top[0]["key"]}'
    assert link in response.content.decode()


def test_home_shows_recent_inquiries_without_half_typed_ones(sales, django_user_model):
    user = django_user_model.objects.get(username="sales")
    part = PartFactory(sku="FIT-BPD-00001")
    for raw, key in [("2044", "2044"), ("20443906", "20443906")]:
        Inquiry.objects.create(input_type="text", raw_input=raw, query_key=key,
                               matched_part=part, created_by=user)
    Inquiry.objects.create(input_type="image", created_by=user)

    response = sales.get(HOME)

    shown = [i.raw_input for i in response.context["inquiries"]]
    assert shown == ["", "20443906"]  # the photo inquiry and the finished search
    assert "📷 照片询价" in response.content.decode()


def test_home_on_an_empty_database_explains_what_to_do(sales):
    body = sales.get(HOME).content.decode()

    assert "seed_demo" in body and "还没有询价记录" in body


def test_home_marks_demo_mode(sales, settings):
    settings.LLM_PROVIDER = "mock"
    assert "演示模式" in sales.get(HOME).content.decode()

    settings.LLM_PROVIDER = "openai_compatible"
    assert "演示模式" not in sales.get(HOME).content.decode()


def test_home_stays_within_a_query_budget(sales, django_assert_max_num_queries):
    for i in range(20):
        PartFactory(sku=f"FIT-TST-{i:05d}")

    # session + user + summary aggregate + duplicate groups + pending count + inquiries
    with django_assert_max_num_queries(6):
        sales.get(HOME)
