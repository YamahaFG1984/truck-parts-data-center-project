import io
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from apps.catalog.models import Part, PartNumber
from apps.catalog.tests.factories import (
    BrandFactory,
    CategoryFactory,
    PartFactory,
    PartNumberFactory,
)
from apps.importer.models import ImportBatch, ImportRow
from apps.importer.services import importing
from apps.importer.services.importing import ImportFailed, dry_run, execute
from apps.importer.services.loader import read_table
from apps.importer.services.mapping import suggest_mapping
from apps.suppliers.models import SupplierOffer
from apps.suppliers.tests.factories import SupplierFactory, SupplierOfferFactory
from scripts.make_supplier_excel import write_supplier_excel

from .test_loader_and_upload import _xlsx_bytes

pytestmark = pytest.mark.django_db
HEADERS = [
    "Part No.", "OEM NO", "Ref", "Description", "适用车型", "MOQ", "FOB Price(USD)", "Packing",
]


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def make_batch(rows, *, supplier=True, overwrite=False, headers=HEADERS, data=None) -> ImportBatch:
    """A mapped batch built from rows (or ready-made xlsx bytes), mapping from synonyms."""
    data = data or _xlsx_bytes([headers, *rows])
    batch = ImportBatch(original_name="q.xlsx", supplier=SupplierFactory() if supplier else None)
    batch.file.save("q.xlsx", ContentFile(data), save=True)
    table = read_table(io.BytesIO(data), "q.xlsx")
    batch.column_mapping = {"columns": suggest_mapping(table.headers, table.rows),
                            "overwrite": overwrite}
    batch.save()
    return batch


def row(pn="HB-1", oe="20443906", ref="", desc="Brake Pad Set", vehicle="Volvo FH12", moq="50pcs",
        price="18.50", packing="20pcs/ctn"):
    return [pn, oe, ref, desc, vehicle, moq, price, packing]


# --- the demo supplier file end to end -----------------------------------------------------------


@pytest.fixture
def catalog_and_messy_file(tmp_path):
    volvo = BrandFactory(name="Volvo")
    samples = []
    for i in range(10):
        part = PartFactory(sku=f"FIT-BPD-{i:05d}")
        pn = PartNumberFactory(part=part, number=f"2{i:07d}", kind="OE", brand=volvo)
        samples.append({"oe": pn.number, "name_en": part.name_en, "vehicle": "Volvo FH12"})
    taken = set(PartNumber.objects.values_list("number_norm", flat=True))
    return write_supplier_excel(tmp_path / "messy.xlsx", samples, taken, seed=7).read_bytes()


def test_messy_supplier_file_dry_run_matches_execute(catalog_and_messy_file):
    batch = make_batch(None, data=catalog_and_messy_file)
    parts_before = Part.objects.count()

    planned = dry_run(batch).counts
    assert Part.objects.count() == parts_before  # dry run wrote nothing
    assert planned == {"new": 70, "updated": 10, "skipped": 0, "duplicate": 0, "invalid": 0}

    done = execute(batch).counts

    assert done == planned
    assert Part.objects.count() == parts_before + 70
    assert SupplierOffer.objects.filter(supplier=batch.supplier).count() == 80  # every row priced
    assert ImportRow.objects.filter(batch=batch).count() == 80
    batch.refresh_from_db()
    assert batch.status == "done" and batch.stats["result"] == done
    new_parts = Part.objects.filter(sku__startswith="FIT-GEN-")
    assert new_parts.count() == 70 and not new_parts.filter(completeness_score=0).exists()
    assert set(new_parts.values_list("status", "source").distinct()) == {("draft", "import")}


def test_whole_wizard_through_the_views(admin_client, catalog_and_messy_file):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from .test_loader_and_upload import XLSX

    supplier = SupplierFactory()
    admin_client.post(reverse("importer:upload"), {
        "file": SimpleUploadedFile("q.xlsx", catalog_and_messy_file, content_type=XLSX),
        "supplier": supplier.pk,
    })
    batch = ImportBatch.objects.get()
    admin_client.get(reverse("importer:mapping", args=[batch.pk]))
    fields = {f"field_{i}": c["field"]
              for i, c in enumerate(ImportBatch.objects.get().column_mapping["columns"])}

    saved = admin_client.post(reverse("importer:mapping", args=[batch.pk]), fields)
    preview = admin_client.get(saved.url)
    done = admin_client.post(reverse("importer:execute", args=[batch.pk]), follow=True)

    assert saved.url == reverse("importer:dry_run", args=[batch.pk])
    assert "确认导入 80 行" in preview.content.decode()
    assert done.redirect_chain[-1][0] == reverse("importer:result", args=[batch.pk])
    assert "导入完成：新增 70，更新 10" in done.content.decode()
    result_url = reverse("importer:result", args=[batch.pk])
    only_updated = admin_client.get(result_url, {"result": "updated"})
    assert len(only_updated.context["rows"]) == 10


# --- identification and results ------------------------------------------------------------------


def test_new_part_gets_numbers_brand_fitment_packaging_and_offer():
    batch = make_batch([row(ref="K001234", desc="刹车片 Brake Pad Set",
                            vehicle="Volvo FH12/FH16", price="USD 18.5")])

    execute(batch)

    part = Part.objects.get(sku="FIT-GEN-00001")
    assert (part.name_en, part.name_zh) == ("Brake Pad Set", "刹车片")
    numbers = {(n.number, n.kind, n.brand.name if n.brand else None) for n in part.numbers.all()}
    assert numbers == {("20443906", "OE", "Volvo"), ("K001234", "CROSS", "Knorr-Bremse"),
                       ("HB-1", "SUPPLIER", None)}
    assert sorted(str(f) for f in part.fitments.all()) == ["Volvo FH12", "Volvo FH16"]
    assert part.packaging == {"pcs_per_carton": 20, "unit": "pc"}
    offer = part.offers.get()
    assert (offer.unit_cost_usd, offer.moq, offer.price_term) == (Decimal("18.50"), 50, "FOB")


def test_sku_numbering_continues_and_uses_the_category_code():
    PartFactory(sku="FIT-GEN-00007")
    CategoryFactory(name="刹车片", code="BPD")
    batch = make_batch(
        [["20443906", "刹车片"], ["20443907", ""]], headers=["OEM NO", "分类"],
    )

    report = execute(batch)

    assert [p.new_sku for p in report.plans] == ["FIT-BPD-00001", "FIT-GEN-00008"]


@pytest.mark.parametrize(
    ("values", "reason"),
    [(row(pn="", oe="", ref="K001234"), "缺少 SKU、OE 号和供应商料号"),
     (row(oe="9.86E+08"), "科学计数"),
     (row(oe=""), "没有选择供应商")],
)
def test_invalid_rows_explain_why(values, reason):
    batch = make_batch([values], supplier=reason != "没有选择供应商")

    [plan] = dry_run(batch).plans

    assert plan.result == "invalid" and reason in plan.message


def test_number_on_two_parts_is_a_suspected_duplicate_and_not_imported():
    a, b = PartFactory(sku="FIT-A"), PartFactory(sku="FIT-B")
    PartNumberFactory(part=a, number="20443906", kind="OE")
    PartNumberFactory(part=b, number="2044-3906", kind="OE")
    batch = make_batch([row()])

    report = execute(batch)

    assert report.plans[0].result == "duplicate"
    assert "FIT-A、FIT-B" in report.plans[0].message
    assert not SupplierOffer.objects.exists()


def test_same_number_twice_in_one_file_is_imported_once():
    batch = make_batch([row(pn="HB-1"), row(pn="HB-2", oe="2044 3906")])

    report = execute(batch)

    assert [p.result for p in report.plans] == ["new", "skipped"]
    assert "第 2 行" in report.plans[1].message
    assert Part.objects.count() == 1


def test_reimporting_the_same_file_changes_nothing():
    rows = [row(), row(pn="HB-2", oe="20568713")]
    execute(make_batch(rows))
    first_supplier = SupplierOffer.objects.first().supplier

    second = make_batch(rows)
    second.supplier = first_supplier
    second.save()
    report = execute(second)

    assert report.counts["skipped"] == 2
    assert Part.objects.count() == 2


def test_prices_without_supplier_or_in_rmb_are_not_imported():
    no_supplier = dry_run(make_batch([row()], supplier=False)).plans[0]
    rmb = dry_run(make_batch([row(price="¥128")])).plans[0]

    assert "未选择供应商，价格未导入" in no_supplier.message
    assert "CNY" in rmb.message
    execute(make_batch([row(price="¥128")]))
    assert not SupplierOffer.objects.exists()


# --- update rules --------------------------------------------------------------------------------


def _existing(**fields):
    part = PartFactory(**fields)
    PartNumberFactory(part=part, number="20443906", kind="OE")
    return part


def test_default_only_fills_blanks():
    part = _existing(name_en="Old Name", packaging={})

    execute(make_batch([row(desc="New Name")]))

    part.refresh_from_db()
    assert part.name_en == "Old Name" and part.packaging == {"pcs_per_carton": 20, "unit": "pc"}


def test_overwrite_replaces_unverified_values():
    part = _existing(name_en="Old Name")

    execute(make_batch([row(desc="New Name")], overwrite=True))

    part.refresh_from_db()
    assert part.name_en == "New Name"


def test_verified_part_is_never_overwritten():
    part = _existing(name_en="Checked Name", verified=True)

    report = execute(make_batch([row(desc="New Name")], overwrite=True))

    part.refresh_from_db()
    assert part.name_en == "Checked Name"
    assert report.plans[0].result == "updated"  # other data (offer, fitment) still added


def test_verified_numbers_are_left_untouched():
    part = PartFactory()
    pn = PartNumberFactory(part=part, number="20443906", kind="OE", verified=True,
                           confidence=Decimal("1.00"), source="manual")

    execute(make_batch([row(oe="2044-3906")], overwrite=True))

    pn.refresh_from_db()
    assert (pn.number, pn.source, pn.verified) == ("20443906", "manual", True)
    assert part.numbers.filter(kind="OE").count() == 1


def test_existing_offer_same_day_is_updated_not_duplicated():
    part = _existing()
    supplier = SupplierFactory()
    import datetime as dt

    SupplierOfferFactory(part=part, supplier=supplier, quoted_at=dt.date.today(),
                         unit_cost_usd=Decimal("20.00"))
    batch = make_batch([row(price="18.50")])
    batch.supplier = supplier
    batch.save()

    execute(batch)

    assert list(part.offers.values_list("unit_cost_usd", flat=True)) == [Decimal("18.50")]


# --- transaction ---------------------------------------------------------------------------------


def test_error_in_any_row_rolls_back_the_whole_batch(monkeypatch):
    real_apply = importing._Planner.apply
    calls = []

    def flaky(self, plan):
        calls.append(plan.row_no)
        if len(calls) == 3:
            raise RuntimeError("disk full")
        return real_apply(self, plan)

    monkeypatch.setattr(importing._Planner, "apply", flaky)
    batch = make_batch([row(pn=f"HB-{i}", oe=f"2044390{i}") for i in range(5)])

    with pytest.raises(ImportFailed, match="已全部回滚"):
        execute(batch)

    assert not Part.objects.exists()
    assert not ImportRow.objects.exists()
    assert not SupplierOffer.objects.exists()
    batch.refresh_from_db()
    assert batch.status == "failed" and "disk full" in batch.error


def test_failed_import_shows_message_and_returns_to_dry_run(admin_client, monkeypatch):
    monkeypatch.setattr(importing._Planner, "apply",
                        lambda self, plan: (_ for _ in ()).throw(RuntimeError("boom")))
    batch = make_batch([row()])

    response = admin_client.post(reverse("importer:execute", args=[batch.pk]), follow=True)

    assert response.redirect_chain[-1][0] == reverse("importer:dry_run", args=[batch.pk])
    assert "已全部回滚" in response.content.decode()


def test_demo_reset_still_works_after_an_import():
    from io import StringIO

    from django.core.management import call_command

    call_command("seed_demo", "--parts", "10", stdout=StringIO())
    execute(make_batch([row()]))

    call_command("seed_demo", "--parts", "10", "--reset", stdout=StringIO())

    assert not ImportBatch.objects.exists()
    assert Part.objects.count() == 10
