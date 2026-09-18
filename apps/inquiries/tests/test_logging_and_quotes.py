import datetime as dt
from decimal import Decimal
from io import BytesIO

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.catalog.tests.factories import PartFactory, PartImageFactory, PartNumberFactory
from apps.inquiries.models import Inquiry, QuoteLine
from apps.inquiries.services.logging import query_key
from apps.inquiries.services.quoting import QuoteError, build_quote, quote_to_xlsx
from apps.suppliers.tests.factories import SupplierFactory, SupplierOfferFactory

pytestmark = pytest.mark.django_db
SEARCH = reverse("catalog:search")


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def pad():
    part = PartFactory(sku="FIT-BPD-00001", name_en="Brake Pad Set", title_en="Brake Pad for Volvo",
                       attributes={"length_mm": 210},
                       packaging={"unit": "set", "pcs_per_carton": 20, "gross_weight_kg": 12.5})
    PartNumberFactory(part=part, number="20443906", kind="OE")
    PartImageFactory(part=part)
    SupplierOfferFactory(part=part, supplier=SupplierFactory(name="Hebei Demo Brake"),
                         unit_cost_usd=Decimal("17.90"), moq=50, lead_days=25)
    return part


@pytest.fixture
def sales(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("sales", password="x"))
    return client


# --- logging -------------------------------------------------------------------------------------


def test_every_search_is_logged_with_the_top_hit(sales, pad):
    response = sales.get(SEARCH, {"q": "2044-3906"})

    inquiry = Inquiry.objects.get()
    assert (inquiry.input_type, inquiry.raw_input, inquiry.query_key) == (
        "text", "2044-3906", "20443906")
    assert inquiry.matched_part == pad and inquiry.status == "open"
    assert inquiry.finding["hits"] == 1 and inquiry.candidate_part_ids == [pad.pk]
    assert f"询价 #{inquiry.pk}" in response.content.decode()


def test_logging_is_exactly_one_insert_and_no_extra_read(sales, pad):
    with CaptureQueriesContext(connection) as queries:
        sales.get(SEARCH, {"q": "20443906"})

    sqls = [q["sql"] for q in queries.captured_queries]
    writes = [sql for sql in sqls if sql.startswith(("INSERT", "UPDATE"))]
    reads = [sql for sql in sqls if "inquiries_inquiry" in sql]
    assert len(writes) == 1 and writes[0].startswith('INSERT INTO "inquiries_inquiry"')
    assert reads == writes


def test_empty_query_logs_nothing(sales):
    sales.get(SEARCH)
    sales.get(SEARCH, {"q": "   "})

    assert not Inquiry.objects.exists()


def test_misses_are_logged_without_a_product(sales, pad):
    sales.get(SEARCH, {"q": "99999999"})

    assert Inquiry.objects.get().matched_part is None


@pytest.mark.parametrize(("raw", "key"), [
    ("2044-3906", "20443906"), ("oe:20 443 906", "20443906"), ("２０４４－３９０６", "20443906"),
    ("Brake  PAD volvo", "brakepadvolvo"), ("FIT-bpd-00001", "fitbpd00001"),
    ("刹车片 沃尔沃", "刹车片沃尔沃"), ("2149-", "2149"),
])
def test_query_key_merges_spellings(raw, key):
    assert query_key(raw) == key


def _typed(user, text, seconds_ago, part=None):
    inquiry = Inquiry.objects.create(input_type="text", raw_input=text, query_key=query_key(text),
                                     created_by=user, matched_part=part)
    Inquiry.objects.filter(pk=inquiry.pk).update(
        created_at=timezone.now() - dt.timedelta(seconds=seconds_ago))
    return inquiry


def test_half_typed_searches_are_hidden_but_kept(django_user_model):
    alice = django_user_model.objects.create_user("alice")
    bob = django_user_model.objects.create_user("bob")
    for text, ago in [("20443", 30), ("204439", 28), ("20443906", 26)]:
        _typed(alice, text, ago)
    _typed(bob, "20443", 29)  # another person: not a continuation of alice's typing
    _typed(alice, "2044", 300)  # an hour-old search is its own question

    settled = sorted(Inquiry.objects.settled().values_list("created_by__username", "raw_input"))

    assert settled == [("alice", "2044"), ("alice", "20443906"), ("bob", "20443")]
    assert Inquiry.objects.count() == 5


def test_unmatched_top_counts_settled_misses_by_key(django_user_model, pad):
    user = django_user_model.objects.create_user("u")
    searches = [(4000, "1111-2222"), (3000, "11112222"), (2000, "1111 2222"), (1000, "33334444")]
    for ago, text in searches:
        _typed(user, text, ago)
    _typed(user, "20443906", 500, part=pad)  # a hit, not a miss
    _typed(user, "5555", 100), _typed(user, "55556666", 90)  # "5555" was typed over
    _typed(user, "77778888", 60 * 60 * 24 * 40)  # older than 30 days

    top = list(Inquiry.objects.unmatched_top())

    assert [(row["query_key"], row["times"]) for row in top] == [
        ("11112222", 3), ("55556666", 1), ("33334444", 1)]


def test_list_page_filters_and_shows_the_miss_board(sales, pad):
    sales.get(SEARCH, {"q": "20443906"})
    sales.get(SEARCH, {"q": "99990000"})

    everything = sales.get(reverse("inquiries:list"))
    misses = sales.get(reverse("inquiries:list"), {"hit": "no"})

    assert everything.context["paginator"].count == 2
    assert [i.raw_input for i in misses.context["inquiries"]] == ["99990000"]
    assert [r["query_key"] for r in everything.context["unmatched"]] == ["99990000"]


def test_text_inquiry_can_be_repointed_to_another_candidate(sales, pad):
    twin = PartFactory(sku="FIT-BPD-00002")
    PartNumberFactory(part=twin, number="2044 3906", kind="OE")
    SupplierOfferFactory(part=twin)
    sales.get(SEARCH, {"q": "20443906"})
    inquiry = Inquiry.objects.get()

    sales.post(reverse("inquiries:confirm", args=[inquiry.pk]), {"part": twin.pk})

    inquiry.refresh_from_db()
    assert (inquiry.matched_part, inquiry.status) == (twin, "matched")


# --- quotes --------------------------------------------------------------------------------------


def _inquiry(part):
    return Inquiry.objects.create(input_type="text", raw_input="20443906", matched_part=part)


def test_price_is_cheapest_cost_times_one_plus_margin(pad):
    SupplierOfferFactory(part=pad, unit_cost_usd=Decimal("19.00"))
    inquiry = _inquiry(pad)

    line = build_quote(inquiry, pad, qty=100, margin=Decimal("0.25"))

    assert (line.unit_cost_usd, line.unit_price_usd, line.amount_usd) == (
        Decimal("17.90"), Decimal("22.38"), Decimal("2238.00"))  # 17.90 x 1.25 = 22.375
    assert line.note == "" and inquiry.status == "quoted"
    money = (line.unit_cost_usd, line.margin, line.unit_price_usd)
    assert all(isinstance(v, Decimal) for v in money)


def test_quantity_below_moq_is_noted_not_refused(pad):
    line = build_quote(_inquiry(pad), pad, qty=10)

    assert line.note == "低于起订量（MOQ 50）" and line.margin == Decimal("0.25")


@pytest.mark.parametrize(("qty", "margin", "message"), [(0, "0.25", "数量"), (5, "-0.1", "毛利率")])
def test_bad_quote_input(pad, qty, margin, message):
    with pytest.raises(QuoteError, match=message):
        build_quote(_inquiry(pad), pad, qty=qty, margin=Decimal(margin))


def test_part_without_offers_cannot_be_quoted():
    part = PartFactory()

    with pytest.raises(QuoteError, match="还没有供应商报价"):
        build_quote(_inquiry(part), part, qty=5)


def test_quote_is_a_snapshot(pad):
    line = build_quote(_inquiry(pad), pad, qty=50)
    pad.offers.update(unit_cost_usd=Decimal("30.00"))

    line.refresh_from_db()
    assert line.unit_price_usd == Decimal("22.38")


def test_excel_quotation_opens_and_has_every_line(pad):
    inquiry = _inquiry(pad)
    alt = PartFactory(sku="FIT-BPD-00077")
    PartNumberFactory(part=alt, number="20443906", kind="OE")
    build_quote(inquiry, pad, qty=100)
    build_quote(inquiry, pad, qty=10)

    wb = load_workbook(BytesIO(quote_to_xlsx(inquiry, include_costs=True)))

    sheet = wb["Quotation"]
    rows = [r for r in sheet.iter_rows(min_row=5, values_only=True) if r[2]]
    assert [(r[2], r[7], r[8], r[9]) for r in rows] == [
        ("FIT-BPD-00001", 100, 22.38, 2238.0), ("FIT-BPD-00001", 10, 22.38, 223.8)]
    assert rows[0][3] == "Brake Pad for Volvo" and "OE 20443906" in rows[0][4]
    assert "20 set/ctn" in rows[0][6] and rows[0][12] == "FIT-BPD-00077"
    assert rows[1][13] == "低于起订量（MOQ 50）"
    assert len(sheet._images) == 2  # product photo per line
    assert list(sheet.iter_rows(values_only=True))[-1][8:10] == ("Total", 2461.8)
    internal = list(wb["Internal"].iter_rows(min_row=2, values_only=True))
    sku, supplier, supplier_pn, cost = internal[0][:4]
    assert (sku, supplier, cost) == ("FIT-BPD-00001", "Hebei Demo Brake", 17.9)
    assert supplier_pn.startswith("HB-")


def test_excel_for_someone_without_cost_access_has_no_internal_sheet(pad):
    inquiry = _inquiry(pad)
    build_quote(inquiry, pad, qty=100)

    wb = load_workbook(BytesIO(quote_to_xlsx(inquiry, include_costs=False)))

    assert wb.sheetnames == ["Quotation"]
    assert "17.9" not in str(list(wb["Quotation"].iter_rows(values_only=True)))


def test_quote_pages(sales, pad):
    sales.get(SEARCH, {"q": "20443906"})
    inquiry = Inquiry.objects.get()
    url = reverse("inquiries:quote", args=[inquiry.pk])

    form = sales.get(url)
    data = {"qty": "80", "margin_percent": "30", "customer": "ACME Trucks"}
    added = sales.post(url, data, follow=True)
    download = sales.get(reverse("inquiries:quote_xlsx", args=[inquiry.pk]))

    expected_initial = {"qty": 50, "customer": "", "margin_percent": Decimal("25.00")}
    assert form.context["form"].initial == expected_initial
    assert "已加入报价单" in added.content.decode()
    line = QuoteLine.objects.get()
    assert (line.qty, line.margin, line.unit_price_usd) == (80, Decimal("0.300"), Decimal("23.27"))
    inquiry.refresh_from_db()
    assert inquiry.customer == "ACME Trucks" and inquiry.status == "quoted"
    assert download["Content-Disposition"] == f'attachment; filename="quotation-{inquiry.pk}.xlsx"'
    assert load_workbook(BytesIO(download.content)).sheetnames == ["Quotation", "Internal"]


def test_quote_needs_a_product_first(sales):
    inquiry = Inquiry.objects.create(input_type="text", raw_input="99999999")

    response = sales.get(reverse("inquiries:quote", args=[inquiry.pk]), follow=True)

    assert "请先确认是哪个产品" in response.content.decode()


def test_quote_form_shows_a_friendly_error_without_offers(sales):
    part = PartFactory()
    inquiry = _inquiry(part)

    response = sales.post(reverse("inquiries:quote", args=[inquiry.pk]),
                          {"qty": "5", "margin_percent": "25"})

    assert "还没有供应商报价" in response.content.decode() and not QuoteLine.objects.exists()


def test_submitting_the_form_with_its_defaults_works(sales, pad):
    """What most people do: open the form and press the button without editing."""
    import re

    inquiry = _inquiry(pad)
    url = reverse("inquiries:quote", args=[inquiry.pk])
    page = sales.get(url).content.decode()
    defaults = dict(re.findall(r'name="(qty|margin_percent|customer)" value="([^"]*)"', page))

    response = sales.post(url, defaults)

    assert response.status_code == 302, response.context["form"].errors
    assert QuoteLine.objects.get().margin == Decimal("0.250")


def test_a_typing_burst_leaves_only_its_last_row(django_user_model):
    """What the browser really sends: short text-like prefixes, then the full number,
    sometimes twice (input and search events)."""
    user = django_user_model.objects.create_user("u")
    for ago, text in [(20, "2149"), (19, "2149-"), (18, "2149-5"), (17, "2149-5672"),
                      (16, "2149-5672")]:
        _typed(user, text, ago)

    settled = list(Inquiry.objects.settled().values_list("raw_input", flat=True))

    assert settled == ["2149-5672"]
