import hashlib

import pytest

from apps.archive.models import DecisionLog, FieldChoice, Membership, Product, ReviewItem
from apps.archive.services import matching, review
from apps.archive.services.review import ReviewError
from apps.sources.models import SourceRecord

from .conftest import find_item

pytestmark = pytest.mark.django_db


def product_of(key):
    return review.membership_of(SourceRecord.objects.get(record_key=key)).product


def test_confirming_same_merges_the_two_products(archive, user):
    item = find_item("X-001~Y-001")
    x, y = product_of("X-001"), product_of("Y-001")

    survivor = review.confirm_same(item, user, "对照图片确认")

    x.refresh_from_db(), y.refresh_from_db()
    assert survivor == x and x.status == "grouped"
    assert (y.status, y.merged_into) == ("merged", x)
    assert product_of("Y-001") == x and x.memberships.count() == 2
    item.refresh_from_db()
    assert (item.status, item.decided_by, item.note) == ("same", user, "对照图片确认")
    log = DecisionLog.objects.get(action="merge")
    assert log.review_item == item and log.payload["absorbed"] == y.code


def test_pairs_answered_by_earlier_merges_are_closed(archive, user):
    review.confirm_same(find_item("X-001~Y-001"), user)
    review.confirm_same(find_item("Y-001~Y-008"), user)

    implied = find_item("X-001~Y-008", status=None)
    assert implied.status == "same" and "推出" in implied.note


def test_a_merge_across_a_different_decision_is_refused(archive, user):
    review.mark_different(find_item("X-005~Y-008"), user, "图片不同")
    review.confirm_same(find_item("X-001~X-005"), user)

    with pytest.raises(ReviewError, match="已被判为不同产品"):
        review.confirm_same(find_item("X-001~Y-008"), user)

    assert product_of("X-001") != product_of("Y-008")
    assert find_item("X-001~Y-008").status == "open"


def test_different_changes_no_product_and_is_not_asked_again(archive, user):
    products = Product.objects.count()

    review.mark_different(find_item("X-006~Y-003"), user)
    matching.rematch()

    assert Product.objects.count() == products
    with pytest.raises(LookupError):
        find_item("X-006~Y-003")


def test_records_already_together_cannot_be_judged_different(archive, user, monkeypatch):
    """A pair reopens while its records are merged (its evidence changed): judging it
    different must go through an explicit detach first."""
    review.confirm_same(find_item("X-001~Y-001"), user)
    real = matching._hash

    def changed(category, *records):
        digest = real(category, *records)
        if {r.record_key for r in records} == {"X-001", "Y-001"}:
            digest = hashlib.sha256(digest.encode()).hexdigest()
        return digest

    monkeypatch.setattr(matching, "_hash", changed)
    matching.rematch()

    with pytest.raises(ReviewError, match="已在同一产品中"):
        review.mark_different(find_item("X-001~Y-001"), user)


def test_a_record_can_be_confirmed_independent_or_flagged(archive, user):
    product = review.confirm_independent(find_item("X-009"), user)
    assert product.status == "independent"

    flagged = review.mark_needs_info(find_item("Y-011"), user)
    assert flagged.needs_info and flagged.missing_fields == ["moq"]


def test_a_to_be_completed_flag_survives_a_merge(archive, user):
    review.mark_needs_info(find_item("Y-011"), user)

    survivor = review.confirm_same(find_item("Y-004~Y-011"), user)

    assert survivor.needs_info and "moq" in survivor.missing_fields


def test_a_grouped_product_cannot_be_called_independent(archive, user):
    review.confirm_same(find_item("X-011~Y-010"), user)

    with pytest.raises(ReviewError, match="多条成员"):
        review.confirm_independent(find_item("Y-010"), user)


def test_bulk_confirm_takes_strong_items_only_and_logs_each(archive, user):
    strong = list(ReviewItem.objects.filter(status="open", category="strong"))
    other = find_item("X-005~Y-008")

    done, refused = review.bulk_confirm([*strong, other], user)

    assert len(done) == 2 and [i for i, _ in refused] == [other]
    assert DecisionLog.objects.filter(action="merge").count() == 2
    assert find_item("X-005~Y-008").status == "open"


def test_detach_undoes_a_merge_and_reopens_the_pair(archive, user):
    item = find_item("X-001~Y-001")
    review.confirm_same(item, user)
    membership = Membership.objects.get(record_key="Y-001")

    new = review.detach(membership, user, "合并有误")

    assert product_of("Y-001") == new and new.status == "unreviewed"
    assert product_of("X-001").status == "unreviewed"  # back to a single member
    item.refresh_from_db()
    assert item.status == "superseded"
    assert find_item("X-001~Y-001").status == "open"
    assert DecisionLog.objects.get(action="detach").payload["superseded_items"] == [item.pk]


def test_a_lone_member_cannot_be_detached(archive, user):
    with pytest.raises(ReviewError, match="只有这一条成员"):
        review.detach(Membership.objects.get(record_key="X-001"), user)


def test_choose_value_between_members(archive, user):
    product = review.confirm_same(find_item("X-001~Y-001"), user)
    y001 = SourceRecord.objects.get(record_key="Y-001")

    choice = review.choose_value(product, "price", y001, user, "以最近报价为准")

    assert (choice.value, choice.record) == ("46.58", y001)
    with pytest.raises(ReviewError, match="成员"):
        review.choose_value(product, "price", SourceRecord.objects.get(record_key="X-005"), user,
                            "x")
    with pytest.raises(ReviewError, match="依据"):
        review.choose_value(product, "price", y001, user, " ")
    assert FieldChoice.objects.count() == 1


def test_a_decided_item_cannot_be_decided_again(archive, user):
    item = find_item("X-001~Y-001")
    review.confirm_same(item, user)

    with pytest.raises(ReviewError, match="已处理"):
        review.mark_different(item, user)
