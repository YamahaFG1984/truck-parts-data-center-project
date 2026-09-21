from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.sources.models import RecordNumber, SourceFile, SourceRecord
from apps.sources.services import ingest, intake
from apps.sources.services.ingest import IngestError
from apps.sources.services.storage import store_upload
from apps.suppliers.tests.factories import SupplierFactory

from .dataset import workbook_x, workbook_y
from .pdfgen import make_pdf
from .workbooks import HEADERS_A, ROWS, workbook_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("ops", password="x")


def mapped(data, user, supplier=None, name="quote.xlsx", overrides=None) -> SourceFile:
    """Archive, read and confirm the suggested mapping, as a person would."""
    source = store_upload(SimpleUploadedFile(name, data),
                          supplier or SupplierFactory(), user)
    intake.suggestions(source, intake.inspect(source))
    errors, _ = intake.confirm(source, overrides or {}, user)
    assert not errors
    return source


def test_preview_writes_nothing(user):
    source = mapped(workbook_x(), user)

    planned = ingest.preview(source)

    assert len(planned) == 10 and not SourceRecord.objects.exists()
    assert source.status == "previewed" and source.stats["preview"]["rows"] == 10


def test_commit_stores_every_row_with_its_locator_and_lineage(user):
    source = mapped(workbook_x(), user)

    assert ingest.commit(source, user) == 10

    record = SourceRecord.objects.get(record_key="X-002")
    assert (record.locator, record.sheet, record.row_no) == ("Price List!R3", "Price List", 3)
    assert record.raw["Product Description"] == "Side Grille, Left side"
    assert record.cells["Unit Price"] == "H3"
    assert (record.part_type, record.position, record.make, record.model) == (
        "Side Grille", "Left", "Volvo", "VNL")
    assert (record.price, record.currency) == (Decimal("51.0100"), "EUR")
    assert record.fields["price"]["sources"][0] == {"column": "Unit Price", "cell": "H3",
                                                    "raw": "51.01"}
    assert any("与币种 EUR 不一致" in w for w in record.warnings)
    assert source.status == "committed" and source.stats["committed"]["rows"] == 10


def test_numbers_are_indexed_for_search(user):
    ingest.commit(mapped(workbook_x(), user), user)

    record = SourceRecord.objects.get(record_key="X-001")
    assert sorted(record.numbers.values_list("kind", "number_norm")) == [
        ("oe", "OETST1001"), ("source_id", "X001"), ("supplier_sku", "X0100")]


def test_missing_values_are_recorded_not_filled_in(user):
    ingest.commit(mapped(workbook_x(), user), user)

    no_price = SourceRecord.objects.get(record_key="X-009")
    assert no_price.price is None and no_price.currency == ""
    assert {"price", "currency", "oe_numbers"} <= set(no_price.missing)
    bare = SourceRecord.objects.get(record_key="X-010")
    assert {"fitment", "dims"} <= set(bare.missing)


def test_the_other_supplier_style_reads_the_same_way(user):
    ingest.commit(mapped(workbook_y(), user), user)

    right = SourceRecord.objects.get(record_key="Y-009")  # "Side Grille" + Install Side
    assert (right.part_type, right.position) == ("Side Grille", "Right")
    vn = SourceRecord.objects.get(record_key="Y-006")
    assert (vn.make, vn.model, vn.year_from) == ("Volvo", "VN", None)
    assert SourceRecord.objects.get(record_key="Y-011").missing == ["oe_numbers", "moq"]


def test_identity_falls_back_from_record_id_to_sku_to_content(user):
    headers = [h for h in HEADERS_A if h != "Source Record ID"]
    rows = [r[1:] for r in ROWS]
    rows[1][0] = rows[0][0]  # two rows with the same supplier SKU
    source = mapped(workbook_bytes(headers, rows), user)

    ingest.commit(source, user)

    kinds = list(SourceRecord.objects.order_by("row_no").values_list("key_kind", "record_key"))
    assert kinds[0] == ("supplier_sku", "X-01-00")
    assert kinds[1][0] == "content" and kinds[1][1].startswith("#")
    assert any("重复" in w for w in SourceRecord.objects.get(row_no=3).warnings)


def test_rows_without_any_stable_key_are_warned():
    from apps.sources.services.ingest import Planned, _identify
    from apps.sources.services.standardize import Standardized

    item = Planned("S", "S!R2", 2, None, None, {}, {}, Standardized(typed={"supplier_sku": ""},
                                                                      content_hash="ab" * 32))
    _identify(item, {})

    assert item.key_kind == "content" and "无法识别这一条的更新" in item.std.warnings[0]


def test_nothing_is_written_when_the_mapping_is_not_confirmed(user):
    source = store_upload(SimpleUploadedFile("q.xlsx", workbook_x()), SupplierFactory(), user)
    intake.inspect(source)

    with pytest.raises(IngestError, match="列映射尚未确认"):
        ingest.commit(source, user)


def test_a_file_is_committed_once(user):
    source = mapped(workbook_x(), user)
    ingest.commit(source, user)

    with pytest.raises(IngestError, match="已经入库"):
        ingest.commit(source, user)
    assert SourceRecord.objects.count() == 10


def test_a_failure_half_way_leaves_nothing_behind(user, monkeypatch):
    source = mapped(workbook_x(), user)

    def broken(self, objs, *args, **kwargs):
        list(objs)
        raise RuntimeError("disk full")

    monkeypatch.setattr(type(RecordNumber.objects), "bulk_create", broken)
    with pytest.raises(RuntimeError):
        ingest.commit(source, user)

    source.refresh_from_db()
    assert not SourceRecord.objects.exists() and source.status != "committed"


def test_known_identities_wait_for_incremental_import(user):
    supplier = SupplierFactory()
    ingest.commit(mapped(workbook_x(), user, supplier), user)
    again = mapped(workbook_bytes(HEADERS_A, ROWS), user, supplier, name="september.xlsx")

    planned = ingest.preview(again)

    assert planned[0].problem and "M27" in planned[0].problem
    with pytest.raises(IngestError, match="不能入库"):
        ingest.commit(again, user)


def test_pdf_rows_are_located_by_page_table_and_row(user):
    header = ["Source Ref", "Brand Number", "English Name", "Offer Price", "Curr."]
    data = make_pdf([[header, ["Y-101", "Y1X", "Front Grille", "46.58", "USD"]],
                     [["Y-102", "Y2X", "Fan Shroud", "61.9", "USD"]]])
    ingest.commit(mapped(data, user, name="catalog.pdf"), user)

    second = SourceRecord.objects.get(record_key="Y-102")
    assert (second.locator, second.page, second.table_no, second.row_no) == ("P2/T1/R1", 2, 1, 1)
    assert second.fields["name"]["sources"][0]["cell"] == "P2/T1/R1/C3"


class TestPages:
    @pytest.fixture
    def ops(self, client, user):
        client.force_login(user)
        return client

    def test_preview_page_lists_rows_and_commits(self, ops, user):
        source = mapped(workbook_x(), user)
        url = reverse("sources:preview", args=[source.pk])

        body = ops.get(url).content.decode()
        assert "Price List!R3" in body and "缺单价" in body and "确认入库 10 条" in body
        assert not SourceRecord.objects.exists()

        response = ops.post(url, follow=True)
        assert "已入库 10 条来源记录" in response.content.decode()
        assert SourceRecord.objects.count() == 10

    def test_mapping_cannot_change_after_commit(self, ops, user):
        source = mapped(workbook_x(), user)
        ingest.commit(source, user)

        response = ops.post(reverse("sources:mapping", args=[source.pk]), {"field__0__4": "note"},
                            follow=True)

        assert "映射不能再改" in response.content.decode()
        source.refresh_from_db()
        assert source.mapping["sheets"][0]["columns"][4]["field"] == "position"
