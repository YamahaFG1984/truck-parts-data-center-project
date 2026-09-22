"""Incremental import: a supplier's next file is compared with what we already hold
(docs/archive-design.html §10)."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.sources.models import SourceRecord
from apps.sources.services import ingest as ingest_service
from apps.sources.services.storage import DuplicateFile, store_upload
from apps.suppliers.models import Supplier

from .dataset import ingest, ingest_both, workbook_x, workbook_x2

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("ops", password="x")


@pytest.fixture
def first(user):
    x, _ = ingest_both(user)
    return x


@pytest.fixture
def second(first, user):
    return ingest(user, first.supplier, workbook_x2(), "Supplier X 第二版.xlsx", commit=False)


def by_key(plan):
    return {row.record_key: row for row in plan}


def test_the_same_file_again_is_refused(first, user):
    with pytest.raises(DuplicateFile):
        store_upload(SimpleUploadedFile("again.xlsx", workbook_x()), first.supplier, user)


def test_preview_classifies_every_row_and_writes_nothing(second):
    before = SourceRecord.objects.count()
    plan = ingest_service.preview(second)
    rows = by_key(plan)

    assert SourceRecord.objects.count() == before
    assert rows["X-001"].change == "price_update"
    assert rows["X-002"].change == "key_change"
    assert rows["X-004"].change == "info_update"
    assert rows["X-012"].change == "new" and rows["X-012"].previous is None
    assert rows["X-003"].change == "unchanged"
    assert [r.record_key for r in plan.absent] == ["X-010"]
    assert plan.counts().items() >= {"new": 1, "unchanged": 7, "price_update": 1,
                                      "info_update": 1, "key_change": 1, "absent": 1,
                                      "rows": 11}.items()


def test_the_diff_names_each_changed_field_with_old_and_new_values(second):
    rows = by_key(ingest_service.plan(second))

    price = {c["field"]: c for c in rows["X-001"].diff}
    assert price["price"]["old"] == "42.67" and price["price"]["new"] == "45"
    assert {c["kind"] for c in rows["X-001"].diff} == {"quote"}
    position = {c["field"]: c for c in rows["X-002"].diff}["position"]
    assert (position["old"], position["new"], position["kind"]) == ("Left", "Right", "key")
    assert [c["field"] for c in rows["X-004"].diff] == ["supplier_sku"]


def test_commit_writes_new_versions_and_leaves_old_ones_untouched(second, user):
    old = SourceRecord.objects.get(supplier=second.supplier, record_key="X-001")
    old_price, old_file = old.price, old.source_file_id

    written = ingest_service.commit(second, user)

    assert written == 4  # the seven unchanged rows are not written again
    new = SourceRecord.objects.current().get(supplier=second.supplier, record_key="X-001")
    assert (new.version, new.previous_id, new.change_type) == (2, old.pk, "price_update")
    assert new.price == Decimal("45")
    old.refresh_from_db()
    assert (old.price, old.source_file_id) == (old_price, old_file)
    assert SourceRecord.objects.current().get(
        supplier=second.supplier, record_key="X-003").version == 1
    assert SourceRecord.objects.current().get(
        supplier=second.supplier, record_key="X-012").change_type == "new"
    assert SourceRecord.objects.current().get(
        supplier=second.supplier, record_key="X-002").change_type == "key_change"
    committed = second.stats["committed"]
    assert (committed["written"], committed["unchanged"], committed["absent"]) == (4, 7, 1)


def test_a_dropped_record_stays_current(second, user):
    ingest_service.commit(second, user)
    assert SourceRecord.objects.current().filter(supplier=second.supplier,
                                                 record_key="X-010").exists()


def test_versions_are_per_supplier(second, user):
    """Only the supplier who sent the file gets new versions."""
    ingest_service.commit(second, user)
    y = Supplier.objects.get(name="Supplier Y")
    assert set(SourceRecord.objects.filter(supplier=y).values_list("version", flat=True)) == {1}


def test_preview_page_shows_changes_and_what_will_be_written(client, user, second):
    client.force_login(user)
    response = client.get(reverse("sources:preview", args=[second.pk]))
    page = response.content.decode()

    assert "关键字段变化" in page and "报价更新" in page and "本次未出现" in page
    assert "确认入库 4 条" in page and "7 条与上一版相同" in page
    assert "Left" in page and "Right" in page
