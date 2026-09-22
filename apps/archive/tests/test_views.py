import pytest
from django.urls import reverse

from apps.archive.models import DecisionLog, Membership, ReviewItem
from apps.archive.services import review
from apps.sources.models import SourceRecord

from .conftest import find_item

pytestmark = pytest.mark.django_db
QUEUE = reverse("archive:queue")


@pytest.fixture
def ops(client, user):
    client.force_login(user)
    return client


def test_the_queue_groups_connected_pairs(ops, archive):
    response = ops.get(QUEUE)

    clusters = response.context["clusters"]
    grille = next(c for c in clusters
                  if {r.record_key for r in c["records"]} >= {"X-001", "Y-001"})
    assert {r.record_key for r in grille["records"]} == {"X-001", "X-005", "X-006", "Y-001",
                                                           "Y-008"}
    conflict = next(c for c in clusters if find_item("X-006~Y-003") in c["items"])
    assert len(conflict["items"]) == 1  # a conflict does not chain groups together
    assert clusters[0]["strength"] == "strong"  # the easy decisions come first
    assert {i.record_a.record_key for i in response.context["singles"]} == {
        "X-009", "X-010", "Y-006", "Y-010", "Y-011"}
    body = response.content.decode()
    strong = find_item("X-001~Y-001")
    assert f'name="items" value="{strong.pk}"' in body
    assert f'name="items" value="{find_item("X-006~Y-003").pk}"' not in body  # conflicts can't


def test_the_queue_filters_by_category_and_supplier(ops, archive):
    response = ops.get(QUEUE, {"category": "number_conflict"})
    items = [i for c in response.context["clusters"] for i in c["items"]]
    assert {i.category for i in items} == {"number_conflict"} and len(items) == 2

    supplier = SourceRecord.objects.get(record_key="Y-010").supplier
    response = ops.get(QUEUE, {"supplier": supplier.pk})
    items = [i for c in response.context["clusters"] for i in c["items"]]
    assert items and all(supplier.pk in (i.record_a.supplier_id, i.record_b.supplier_id)
                         for i in items)


def test_the_item_page_shows_both_records_with_sources(ops, archive):
    item = find_item("X-006~Y-003")

    body = ops.get(reverse("archive:item", args=[item.pk])).content.decode()

    assert "Front Grille" in body and "Bug Screen" in body
    assert "Product Description · C7" in body and "English Name · C4" in body
    assert "bg-red-50" in body  # conflicting fields are highlighted
    assert "一号多品" in body and "判为不同产品" in body


def test_deciding_from_the_item_page(ops, archive, user):
    item = find_item("X-001~Y-001")

    response = ops.post(reverse("archive:item", args=[item.pk]),
                        {"action": "same", "note": "对照目录确认", "next": QUEUE}, follow=True)

    item.refresh_from_db()
    assert item.status == "same" and item.decided_by == user
    assert "已确认为同一产品" in response.content.decode()
    assert DecisionLog.objects.filter(action="merge", payload__note="对照目录确认").exists()


def test_a_refused_decision_is_explained(ops, archive, user):
    item = find_item("X-009")  # a single record: "same" does not apply

    response = ops.post(reverse("archive:item", args=[item.pk]), {"action": "same"}, follow=True)

    assert "不适用" in response.content.decode()
    assert ReviewItem.objects.get(pk=item.pk).status == "open"


def test_bulk_confirm_from_the_queue(ops, archive):
    strong = list(ReviewItem.objects.filter(status="open", category="strong"))
    other = find_item("X-005~Y-008")

    response = ops.post(reverse("archive:bulk_confirm"),
                        {"items": [i.pk for i in [*strong, other]], "next": QUEUE}, follow=True)

    body = response.content.decode()
    assert "已批量确认 2 条" in body and f"条目 #{other.pk} 未确认" in body


def test_detach_from_the_item_page(ops, archive, user):
    item = find_item("X-001~Y-001")
    review.confirm_same(item, user)
    body = ops.get(reverse("archive:item", args=[item.pk])).content.decode()
    assert "移出 Y-001" in body

    membership = Membership.objects.get(record_key="Y-001")
    response = ops.post(reverse("archive:detach", args=[membership.pk]), {"next": QUEUE},
                        follow=True)

    assert "Y-001 已移出" in response.content.decode()
    assert find_item("X-001~Y-001").status == "open"


def test_review_pages_need_login(client):
    assert client.get(QUEUE).status_code == 302
