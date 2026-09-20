import csv
from decimal import Decimal
from io import StringIO

import pytest
from django.urls import reverse

from apps.catalog.models import Brand, Part
from apps.catalog.tests.factories import (
    CategoryFactory,
    FitmentFactory,
    PartFactory,
    PartImageFactory,
    PartNumberFactory,
)
from apps.inquiries.services.export import eligible, to_alibaba_csv, to_shopify_csv
from apps.suppliers.tests.factories import SupplierFactory, SupplierOfferFactory

pytestmark = pytest.mark.django_db
EXPORT = reverse("inquiries:export")
PART_LIST = reverse("catalog:part_list")


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def sales(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("sales", password="x"))
    return client


def brand(name: str) -> Brand:
    """Brand names are unique, so several parts must share one row."""
    return Brand.objects.get_or_create(name=name)[0]


def listed_part(**kwargs) -> Part:
    """A part that passes the export rules: reviewed and with a main image."""
    part = PartFactory(**{
        "sku": "FIT-BPD-00001",
        "status": Part.Status.REVIEWED,
        "name_en": "Brake Pad Set",
        "title_en": "Brake Pad Set for Volvo FH12, OE 20443906",
        "description_en": 'Heavy duty pad, "premium" grade.\nFits front axle, 210 mm.',
        "selling_points": ["Low noise", "Long life"],
        "faq": [{"q": "MOQ?", "a": "50 sets."}],
        "keywords": ["brake pad", "volvo fh12"],
        "attributes": {"length_mm": 210},
        "packaging": {"unit": "set", "pcs_per_carton": 20, "gross_weight_kg": 12.5},
        "category": CategoryFactory(name_en="Brake Pad"),
        **kwargs,
    })
    PartNumberFactory(part=part, number="20443906", kind="OE", brand=brand("Volvo"))
    PartNumberFactory(part=part, number="K001234", kind="CROSS",
                      brand=brand("Knorr-Bremse"))
    FitmentFactory(part=part, make="Volvo", model="FH12")
    PartImageFactory(part=part)
    SupplierOfferFactory(part=part, supplier=SupplierFactory(name=f"Supplier of {part.sku}"),
                         unit_cost_usd=Decimal("17.90"), moq=50, lead_days=25)
    return part


def rows(data: bytes) -> list[dict]:
    assert data.startswith(b"\xef\xbb\xbf")  # utf-8-sig: Excel opens Chinese correctly
    return list(csv.DictReader(StringIO(data.decode("utf-8-sig"))))


def loaded(parts):
    return list(Part.objects.filter(pk__in=[p.pk for p in parts]).with_related())


# --- eligibility -----------------------------------------------------------------------------


def test_reviewed_and_published_with_an_image_are_exportable():
    parts = loaded([listed_part(), listed_part(sku="FIT-BPD-00002",
                                               status=Part.Status.PUBLISHED)])

    exportable, excluded = eligible(parts)

    assert [p.sku for p in exportable] == ["FIT-BPD-00001", "FIT-BPD-00002"]
    assert excluded == []


def test_draft_and_imageless_parts_are_excluded_with_a_reason():
    draft = listed_part(sku="FIT-BPD-00003", status=Part.Status.DRAFT)
    bare = PartFactory(sku="FIT-BPD-00004", status=Part.Status.DRAFT)
    no_image = PartFactory(sku="FIT-BPD-00005", status=Part.Status.REVIEWED)

    exportable, excluded = eligible(loaded([draft, bare, no_image]))

    assert exportable == []
    assert excluded == [
        ("FIT-BPD-00003", "未审核（草稿）"),
        ("FIT-BPD-00004", "未审核（草稿）、缺主图"),
        ("FIT-BPD-00005", "缺主图"),
    ]


def test_eligibility_reads_prefetched_images_only(django_assert_num_queries):
    parts = loaded([listed_part(), listed_part(sku="FIT-BPD-00002")])

    with django_assert_num_queries(0):
        eligible(parts)


# --- Alibaba ---------------------------------------------------------------------------------


def test_alibaba_row_uses_reviewed_listing_fields_and_the_selling_price():
    part = listed_part()

    row = rows(to_alibaba_csv(loaded([part])))[0]

    assert row["Product SKU"] == "FIT-BPD-00001"
    assert row["Product Name"] == part.title_en  # the reviewed listing title, not name_en
    assert row["Category"] == "Brake Pad"
    assert row["Model Number"] == "20443906" and row["OE Number"] == "20443906"
    assert row["Cross Reference"] == "Knorr-Bremse K001234"
    assert row["Applicable Vehicle"] == "Volvo FH12 1993–2005"
    assert row["Specification"] == "length_mm: 210"
    assert row["Keywords"] == "brake pad, volvo fh12"
    assert row["Selling Points"] == "- Low noise\n- Long life"
    assert row["Unit Type"] == "set" and row["Minimum Order Quantity"] == "50"
    assert row["FOB Price (USD)"] == "22.38"  # 17.90 x 1.25, half-up
    assert row["Lead Time (days)"] == "25"
    assert row["Packaging Details"] == "20 set/carton; G.W. 12.5 kg"
    assert row["Main Image URL"] == part.images.get().image.url


def test_supplier_and_cost_never_reach_a_platform_file():
    part = listed_part()
    supplier = part.offers.get().supplier.name

    body = to_alibaba_csv(loaded([part])).decode("utf-8-sig")

    assert supplier not in body and "17.90" not in body


def test_quotes_and_newlines_inside_a_description_survive_the_round_trip():
    part = listed_part()

    row = rows(to_alibaba_csv(loaded([part])))[0]

    assert row["Product Description"] == part.description_en
    assert '"premium"' in row["Product Description"] and "\n" in row["Product Description"]


def test_image_url_is_absolute_when_a_base_url_is_given():
    part = listed_part()

    row = rows(to_alibaba_csv(loaded([part]), base_url="https://demo.example/"))[0]

    assert row["Main Image URL"] == f"https://demo.example{part.images.get().image.url}"


def test_a_part_without_offers_exports_with_empty_price_columns():
    part = PartFactory(sku="FIT-BPD-00006", status=Part.Status.REVIEWED, name_en="Air Dryer")
    PartImageFactory(part=part)

    row = rows(to_alibaba_csv(loaded([part])))[0]

    assert row["Product Name"] == "Air Dryer"  # falls back to name_en
    assert row["FOB Price (USD)"] == "" and row["Minimum Order Quantity"] == ""
    assert row["Model Number"] == "FIT-BPD-00006"  # no OE number yet
    assert row["Unit Type"] == "piece"


# --- Shopify ---------------------------------------------------------------------------------


def test_shopify_row_follows_the_product_template():
    part = listed_part()

    data = to_shopify_csv(loaded([part]))
    header = data.decode("utf-8-sig").splitlines()[0]
    row = rows(data)[0]

    assert header.startswith("Handle,Title,Body (HTML),Vendor,Type,Tags")
    assert row["Handle"] == "fit-bpd-00001" and row["Variant SKU"] == part.sku
    assert row["Variant Price"] == "22.38" and row["Variant Grams"] == "12500"
    assert row["Tags"] == "brake pad, volvo fh12, 20443906"
    assert row["Status"] == "draft"  # reviewed but not published yet
    assert row["Image Src"] == part.images.get().image.url


def test_shopify_body_is_html_and_escapes_the_description():
    part = listed_part(description_en='Pad with <script>alert(1)</script> & "quotes"')

    body = rows(to_shopify_csv(loaded([part])))[0]["Body (HTML)"]

    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "<li>Low noise</li>" in body and "<td>20443906</td>" in body
    assert "<strong>MOQ?</strong>" in body


def test_published_parts_are_active_in_shopify():
    part = listed_part(status=Part.Status.PUBLISHED)

    assert rows(to_shopify_csv(loaded([part])))[0]["Status"] == "active"


# --- the export view -------------------------------------------------------------------------


def test_export_downloads_a_csv_attachment(sales):
    part = listed_part()

    response = sales.post(EXPORT, {"parts": [part.pk], "platform": "alibaba"})

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=\"alibaba-listing-" in response["Content-Disposition"]
    assert rows(response.content)[0]["Product SKU"] == part.sku


def test_excluded_skus_are_reported_in_the_next_page_messages(sales):
    good = listed_part()
    draft = listed_part(sku="FIT-BPD-00009", status=Part.Status.DRAFT)

    response = sales.post(EXPORT, {"parts": [good.pk, draft.pk], "platform": "shopify",
                                   "next": PART_LIST})
    assert [r["Variant SKU"] for r in rows(response.content)] == [good.sku]

    body = sales.get(PART_LIST).content.decode()
    assert "1 个 SKU 未导出：FIT-BPD-00009（未审核（草稿））" in body
    assert "已导出 1 个 SKU 到 Shopify 模板。" in body


def test_nothing_exportable_redirects_back_with_an_error(sales):
    draft = listed_part(sku="FIT-BPD-00010", status=Part.Status.DRAFT)

    response = sales.post(EXPORT, {"parts": [draft.pk], "platform": "alibaba",
                                   "next": PART_LIST}, follow=True)

    assert response.redirect_chain[-1][0] == PART_LIST
    assert "没有可导出的 SKU" in response.content.decode()


def test_unknown_platform_is_refused(sales):
    part = listed_part()

    response = sales.post(EXPORT, {"parts": [part.pk], "platform": "amazon"}, follow=True)

    assert "请选择导出平台" in response.content.decode()


def test_export_of_a_page_of_parts_stays_within_a_query_budget(
    sales, django_assert_max_num_queries
):
    parts = [listed_part(sku=f"FIT-BPD-{i:05d}") for i in range(10)]

    # session + user + parts + numbers + fitments + images + offers = 7
    with django_assert_max_num_queries(7):
        response = sales.post(EXPORT, {"parts": [p.pk for p in parts], "platform": "alibaba"})

    assert len(rows(response.content)) == 10


def test_anonymous_user_is_sent_to_login(client):
    response = client.post(EXPORT, {"platform": "alibaba"})

    assert response.status_code == 302 and reverse("login") in response.url


def test_part_list_offers_both_platforms(sales):
    body = sales.get(PART_LIST).content.decode()

    assert f'formaction="{EXPORT}"' in body
    assert '<option value="alibaba">' in body and '<option value="shopify">' in body


def test_a_foreign_next_url_is_not_followed(sales):
    draft = listed_part(sku="FIT-BPD-00011", status=Part.Status.DRAFT)

    response = sales.post(EXPORT, {"parts": [draft.pk], "platform": "alibaba",
                                   "next": "https://evil.example/pwned"})

    assert response.url == PART_LIST
