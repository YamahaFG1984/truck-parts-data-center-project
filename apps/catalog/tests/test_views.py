import pytest
from django.urls import reverse

from apps.catalog.services.matcher import MAX_RESULTS

from .factories import (
    BRAKE_PAD_SCHEMA,
    BrandFactory,
    CategoryFactory,
    FitmentFactory,
    PartFactory,
    PartImageFactory,
    PartNumberFactory,
)

pytestmark = pytest.mark.django_db
SEARCH = reverse("catalog:search")
HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def user_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("sales", password="x"))
    return client


@pytest.fixture
def pad():
    part = PartFactory(sku="FIT-BPD-00001", name_en="Brake Pad Set, Front Axle",
                       category=CategoryFactory(name="刹车片", attribute_schema=BRAKE_PAD_SCHEMA),
                       attributes={"length_mm": 210, "friction_material": "ceramic"})
    PartNumberFactory(part=part, number="20443906", kind="OE", brand=BrandFactory(name="Volvo"))
    FitmentFactory(part=part, make="Volvo", model="FH12")
    PartImageFactory(part=part)
    return part


def _card_part(i):
    # Categories with a parent: Category.__str__ reads parent.name, so an
    # unselected parent would cost one query per card.
    category = CategoryFactory(parent=CategoryFactory())
    part = PartFactory(sku=f"FIT-TST-{i:05d}", category=category)
    PartNumberFactory(part=part, number=f"88880{i:03d}", kind="OE")
    PartNumberFactory(part=part, number=f"K{i:06d}", kind="CROSS")
    FitmentFactory(part=part)
    PartImageFactory(part=part)
    return part


def test_anonymous_user_is_sent_to_login(client):
    response = client.get(SEARCH)

    assert response.status_code == 302
    assert reverse("login") in response.url


def test_search_page_without_query_shows_form_and_hint(user_client):
    response = user_client.get(SEARCH)

    body = response.content.decode()
    assert response.status_code == 200
    assert 'name="q"' in body and 'hx-get="' in body
    assert "匹配分三级" in body


def test_search_shows_normalized_match(user_client, pad):
    response = user_client.get(SEARCH, {"q": "2044-3906"})

    body = response.content.decode()
    assert response.status_code == 200
    assert "FIT-BPD-00001" in body
    assert "归一化" in body
    assert reverse("catalog:part_detail", args=[pad.sku]) in body


def test_htmx_request_returns_results_fragment_only(user_client, pad):
    response = user_client.get(SEARCH, {"q": "20443906"}, **HTMX)

    body = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in body and 'name="q"' not in body
    assert "FIT-BPD-00001" in body and "精确" in body


def test_no_result_message(user_client, pad):
    response = user_client.get(SEARCH, {"q": "99999999"}, **HTMX)

    assert "没有找到匹配的产品" in response.content.decode()


def test_overlong_query_is_truncated(user_client):
    response = user_client.get(SEARCH, {"q": "9" * 5000})

    assert response.status_code == 200
    assert response.context["q"] == "9" * 200


def test_search_with_full_page_of_results_stays_within_query_budget(
    user_client, django_assert_max_num_queries
):
    for i in range(MAX_RESULTS + 5):
        _card_part(i)

    # session + user + matcher levels (<=3) + numbers + fitments + images
    with django_assert_max_num_queries(8):
        response = user_client.get(SEARCH, {"q": "88880"})

    assert len(response.context["candidates"]) == MAX_RESULTS


def test_part_detail_shows_numbers_specs_fitment_and_alternatives(user_client, pad):
    twin = PartFactory(sku="FIT-BPD-00099")
    PartNumberFactory(part=twin, number="2044-3906", kind="OE")

    response = user_client.get(reverse("catalog:part_detail", args=[pad.sku]))

    body = response.content.decode()
    assert response.status_code == 200
    assert "20443906" in body and "Volvo" in body and "FH12" in body
    assert "长度" in body and "210 mm" in body  # labelled from the category schema
    assert "宽度" in body and "缺" in body  # required spec missing is flagged
    assert [p.sku for p in response.context["alternatives"]] == ["FIT-BPD-00099"]


def test_part_detail_query_count_is_bounded(user_client, django_assert_max_num_queries, pad):
    for i in range(5):
        alt = _card_part(i)
        PartNumberFactory(part=alt, number="20443906", kind="OE")

    # session, user, part+category, numbers, fitments, images, alternatives + 3 card prefetches
    with django_assert_max_num_queries(10):
        response = user_client.get(reverse("catalog:part_detail", args=[pad.sku]))

    assert len(response.context["alternatives"]) == 5


def test_unknown_sku_is_404(user_client):
    assert user_client.get(reverse("catalog:part_detail", args=["FIT-NOPE-0"])).status_code == 404


def test_staff_sees_admin_edit_link(admin_client, pad):
    response = admin_client.get(reverse("catalog:part_detail", args=[pad.sku]))

    assert reverse("admin:catalog_part_change", args=[pad.pk]) in response.content.decode()
