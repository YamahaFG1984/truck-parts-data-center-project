import datetime as dt
import io
from decimal import Decimal

import pytest

from apps.sources.services.mapping import match_synonym
from apps.sources.services.readers import Cell, Row, read_workbook
from apps.sources.services.standardize import standardize

from .dataset import workbook_x, workbook_y

COLUMNS = {"Name": "name", "Pos": "position", "Fits": "fitment", "OE": "oe_numbers",
           "Size": "dims", "Price": "price", "Cur": "currency", "MOQ": "moq", "Date": "quote_date",
           "Make": "make", "Model": "model", "Year": "years", "Category": "category"}


def std(price_format="", **values):
    """Standardize one row given header -> value; Cell text mimics the reader."""
    cells = {}
    for index, (header, value) in enumerate(values.items()):
        text = value if isinstance(value, str) else str(value)
        coord = f"{'ABCDEFGHIJKLM'[index]}2"
        cells[header] = Cell(value, text, coord, price_format if header == "Price" else "")
    columns = [{"header": h, "field": COLUMNS[h]} for h in values]
    return standardize(Row(2, cells), columns)


@pytest.mark.parametrize(("name", "position", "part_type", "expected_position"), [
    ("Side Grille, Left side", None, "Side Grille", "Left"),
    ("Left Side Grille", None, "Side Grille", "Left"),
    ("Right Side Grille", None, "Side Grille", "Right"),
    ("Side Grille", "Right", "Side Grille", "Right"),  # side only in the position column
    ("Air Filter Housing Cap", None, "Air Filter Housing Cap", None),  # not "Housing"
    ("Air Filter Housing", None, "Air Filter Housing", None),
    ("Front Grille", None, "Front Grille", None),  # "Front" is part of the type, not a side
    ("Headlight Assembly LH", None, "Headlamp", "Left"),
])
def test_part_type_and_position(name, position, part_type, expected_position):
    values = {"Name": name} | ({"Pos": position} if position else {})
    out = std(**values)

    assert out.typed["part_type"] == part_type
    assert (out.typed["position"] or None) == expected_position


def test_position_column_wins_over_the_name_with_a_warning():
    out = std(Name="Left Side Grille", Pos="RH")

    assert out.typed["position"] == "Right"
    assert any("名称中是 Left，位置列是 Right" in w for w in out.warnings)


def test_a_sided_part_without_position_is_missing_it():
    assert "position" in std(Name="Side Grille").missing
    assert "position" not in std(Name="Front Grille").missing


def test_an_unregistered_type_keeps_its_name_and_says_so():
    out = std(Name="Wiper Arm, Left")

    assert (out.typed["part_type"], out.typed["position"]) == ("Wiper Arm", "Left")
    assert out.fields["part_type"]["rule"] == "unregistered" and "不在品类词表" in out.warnings[0]


@pytest.mark.parametrize(("fits", "make", "model", "years"), [
    ("Volvo VNL 2018-2023", "Volvo", "VNL", (2018, 2023)),
    ("Freightliner Cascadia P3", "Freightliner", "Cascadia P3", (None, None)),
    ("Kenworth T680 2019-present", "Kenworth", "T680", (2019, None)),
    ("Volvo Trucks VNR 2021", "Volvo", "VNR", (2021, 2021)),
])
def test_fitment(fits, make, model, years):
    typed = std(Name="Hood", Fits=fits).typed

    assert (typed["make"], typed["model"], (typed["year_from"], typed["year_to"])) == (
        make, model, years)


def test_fitment_without_years_is_a_warning_not_a_missing_field():
    out = std(Name="Hood", Fits="Volvo VN")

    assert "fitment" not in out.missing and any("未注明年份" in w for w in out.warnings)


def test_fitment_from_separate_columns_and_unknown_makes():
    typed = std(Name="Hood", Make="Peterbilt", Model="579", Year="2016-2021").typed
    assert (typed["make"], typed["model"], typed["year_from"]) == ("Peterbilt", "579", 2016)

    out = std(Name="Hood", Fits="Blue Bird Vision 2015")
    assert any("不在整车品牌词表" in w for w in out.warnings)


@pytest.mark.parametrize(("header", "text", "dims"), [
    ("Size", "122 x 75 x 7 cm", ["122.00", "75.00", "7.00"]),
    ("Size", "1220x750x70 mm", ["122.00", "75.00", "7.00"]),
    ("Size", "48 x 30 x 3 in", ["121.92", "76.20", "7.62"]),
])
def test_dimensions_in_cm(header, text, dims):
    assert std(**{"Name": "Hood", header: text}).value("dims") == dims


@pytest.mark.parametrize("text", ["122 x 75 x 7", "122 x 75 cm", "large"])
def test_dimensions_are_not_guessed(text):
    out = std(Name="Hood", Size=text)

    assert out.value("dims") is None and "dims" in out.missing and out.warnings


def test_price_keeps_the_currency_column_and_flags_a_contradicting_format():
    out = std(price_format="$#,##0.00", Name="Hood", Price=51.01, Cur="EUR")

    assert (out.typed["price"], out.typed["currency"]) == (Decimal("51.01"), "EUR")
    assert any("单元格格式显示 $，与币种 EUR 不一致" in w for w in out.warnings)


@pytest.mark.parametrize(("values", "currency"), [
    ({"Price": 12.5, "Cur": "US$"}, "USD"),
    ({"Price": 12.5, "Cur": "RMB"}, "CNY"),
    ({"Price": 12.5, "Cur": "£"}, "GBP"),
    ({"Price": "€12.50"}, "EUR"),  # symbol in the price text itself
    ({"Price": "USD 45.71"}, "USD"),
])
def test_currency_spellings(values, currency):
    assert std(Name="Hood", **values).typed["currency"] == currency


def test_a_price_without_currency_is_never_assumed_to_be_usd():
    out = std(price_format="$#,##0.00", Name="Hood", Price=12.5)

    assert out.typed["currency"] == "" and "currency" in out.missing
    assert any("不据此认定币种" in w for w in out.warnings)
    assert "currency" in std(Name="Hood", Price="$12.50").missing  # "$" is not only USD


def test_a_bare_dollar_sign_in_the_currency_column_is_read_as_usd_with_a_warning():
    out = std(Name="Hood", Price=12.5, Cur="$")

    assert out.typed["currency"] == "USD" and any("加元" in w for w in out.warnings)


@pytest.mark.parametrize(("value", "expected", "warned"), [
    (dt.datetime(2026, 8, 3), dt.date(2026, 8, 3), False),
    ("2026/08/05", dt.date(2026, 8, 5), False),
    ("Aug 5, 2026", dt.date(2026, 8, 5), False),
    ("13/08/2026", dt.date(2026, 8, 13), False),
    ("03/08/2026", None, True),  # day and month cannot be told apart
])
def test_quote_dates(value, expected, warned):
    out = std(Name="Hood", Date=value)

    assert out.typed["quote_date"] == expected and bool(out.warnings) == warned


def test_moq_and_placeholder_blanks():
    assert std(Name="Hood", MOQ="50 pcs").typed["moq"] == 50
    out = std(Name="Hood", MOQ="N/A", OE="-")
    assert out.typed["moq"] is None and {"moq", "oe_numbers"} <= set(out.missing)


def test_several_oe_numbers_in_one_cell():
    assert std(Name="Hood", OE="OE-1001 / OE-1002; OE-1003").value("oe_numbers") == [
        "OE-1001", "OE-1002", "OE-1003"]


def test_every_field_points_back_to_its_cell():
    [sheet] = read_workbook(io.BytesIO(workbook_x()))
    columns = [{"header": h, "field": match_synonym(h)[0]} for h in sheet.headers]

    out = standardize(sheet.rows[1], columns)  # X-002, spreadsheet row 3

    for name, entry in out.fields.items():
        assert entry["sources"], name
    assert out.fields["dims"]["sources"] == [
        {"column": "Package Size", "cell": "G3", "raw": "86 x 36 x 56 cm"}]
    assert out.fields["position"]["sources"][0]["cell"] == "E3"


def test_the_content_hash_ignores_header_wording_but_not_values():
    def hashed(data, index):
        [sheet] = read_workbook(io.BytesIO(data))
        columns = [{"header": h, "field": match_synonym(h)[0]} for h in sheet.headers]
        return standardize(sheet.rows[index], columns).content_hash

    assert hashed(workbook_x(), 0) != hashed(workbook_y(), 0)  # different prices
    same = std(Name="Hood", Price=10, Cur="USD").content_hash
    renamed = standardize(
        Row(2, {"Desc": Cell("Hood", "Hood", "A2"), "Cost": Cell(10, "10", "B2"),
                "Ccy": Cell("USD", "USD", "C2")}),
        [{"header": "Desc", "field": "name"}, {"header": "Cost", "field": "price"},
         {"header": "Ccy", "field": "currency"}]).content_hash
    assert same == renamed
