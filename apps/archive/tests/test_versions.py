"""New versions of known records (docs/archive-design.html §10): quote changes flow
through, key-field changes stop for a person."""

import pytest
from django.urls import reverse

from apps.archive.models import DecisionLog, Membership, ReviewItem
from apps.archive.services import matching, review
from apps.sources.models import SourceRecord
from apps.sources.tests.dataset import ingest, workbook_x2

from .conftest import find_item

pytestmark = pytest.mark.django_db


@pytest.fixture
def grouped(archive, user):
    """X-001 ~ Y-001 and X-002 ~ Y-002 confirmed as the same products."""
    for key in ("X-001~Y-001", "X-002~Y-002"):
        review.confirm_same(find_item(key), user, "对照目录确认")
    return archive


def second_edition(archive, user):
    x, _ = archive
    return ingest(user, x.supplier, workbook_x2(), "Supplier X 第二版.xlsx")


def membership(key):
    return Membership.objects.select_related("product", "current_record").get(record_key=key)


def test_a_price_update_moves_the_membership_and_keeps_the_decision(grouped, user):
    product = membership("X-001").product
    second_edition(grouped, user)

    m = membership("X-001")
    assert (m.product, m.status, m.current_record.version) == (product, "active", 2)
    assert find_item("X-001~Y-001", status="same")
    assert not ReviewItem.objects.filter(kind="key_change", identity_a__endswith=":X-001")


def test_a_key_change_suspends_the_membership_and_asks_a_person(grouped, user):
    product = membership("X-002").product
    second_edition(grouped, user)

    m = membership("X-002")
    assert (m.product, m.status, m.current_record.version) == (product, "suspended", 2)
    item = find_item("X-002")
    assert (item.kind, item.category, item.strength) == ("key_change", "key_change", "conflict")
    assert item.record_a == m.current_record and item.record_b == m.current_record.previous
    assert "位置 Left → Right" in item.triggers[0]
    assert item.conflicts[0]["field"] == "position"
    assert item.suggested_action == matching.rules()["actions"]["key_change"]
    reopened = find_item("X-002~Y-002")
    assert reopened.category == "position_conflict"
    assert reopened.triggers[0].startswith("证据已变化")


def test_a_key_change_of_a_lone_record_needs_no_decision(archive, user):
    second_edition(archive, user)
    assert membership("X-002").status == "active"
    assert not ReviewItem.objects.filter(kind="key_change")


def test_keep_resumes_the_membership(grouped, user):
    second_edition(grouped, user)
    product = review.keep_after_key_change(find_item("X-002"), user, "供应商确认原表位置写错")

    m = membership("X-002")
    assert (m.product, m.status) == (product, "active")
    assert find_item("X-002", status="same")
    assert DecisionLog.objects.filter(action="keep_after_key_change").exists()


def test_split_moves_the_record_to_a_new_product(grouped, user):
    old = membership("X-002").product
    second_edition(grouped, user)
    new = review.split_after_key_change(find_item("X-002"), user, "右侧件，另立产品")

    m = membership("X-002")
    assert m.product == new != old and m.status == "active"
    assert find_item("X-002", status="different")
    assert old.memberships.count() == 1


def test_rematch_leaves_key_change_items_alone(grouped, user):
    second_edition(grouped, user)
    item = find_item("X-002")
    matching.rematch()
    assert find_item("X-002").pk == item.pk


def test_a_second_key_change_replaces_the_open_item(grouped, user):
    second_edition(grouped, user)
    first = find_item("X-002")
    record = membership("X-002").current_record
    review._open_key_change(record, [])
    first.refresh_from_db()
    assert first.status == "superseded"
    assert ReviewItem.objects.filter(kind="key_change", status="open").count() == 1


def test_old_versions_are_still_there(grouped, user):
    second_edition(grouped, user)
    assert SourceRecord.objects.filter(record_key="X-002").count() == 2


def test_the_item_page_offers_keep_or_split(client, grouped, user):
    second_edition(grouped, user)
    client.force_login(user)
    item = find_item("X-002")
    page = client.get(reverse("archive:item", args=[item.pk])).content.decode()
    assert "新版本 v2" in page and "旧版本 v1" in page
    assert 'value="keep"' in page and 'value="split"' in page
    assert "移出 X-002" not in page  # no separate detach block for a key change

    response = client.post(reverse("archive:item", args=[item.pk]), {"action": "keep"})
    assert response.status_code == 302
    assert membership("X-002").status == "active"
