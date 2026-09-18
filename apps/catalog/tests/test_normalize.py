import pytest

from apps.catalog.services.normalize import (
    brand_hint,
    canonical_brand,
    detect_query_kind,
    normalize_number,
    split_numbers,
    split_query_prefix,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20443906", "20443906"),
        ("2044-3906", "20443906"),
        ("20 443 906", "20443906"),
        ("81.50201-6229", "81502016229"),
        ("A 000 420 15 20", "A0004201520"),
        ("wg9100470107", "WG9100470107"),
        ("0 986 424 813", "0986424813"),  # leading zero kept
        ("WK 1080/7", "WK10807"),
        ("HB_2044", "HB2044"),
        ("  K001234 \n", "K001234"),
        ("２０４４３９０６", "20443906"),  # full-width digits
        ("２０４４－３９０６", "20443906"),  # full-width hyphen
        ("Ａ０００ ４２０", "A000420"),  # full-width letter
        ("刹车片", ""),  # pure Chinese has no part number
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_number(raw, expected):
    assert normalize_number(raw) == expected


def test_normalize_number_is_idempotent():
    once = normalize_number("A 000 420 15 20")
    assert normalize_number(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20443906/20568713", ["20443906", "20568713"]),
        ("20443906, 20568713;21024201", ["20443906", "20568713", "21024201"]),
        ("20443906\n20568713", ["20443906", "20568713"]),
        ("20443906、20568713", ["20443906", "20568713"]),
        ("20443906 | 20568713", ["20443906", "20568713"]),
        ("20443906，20568713", ["20443906", "20568713"]),  # full-width comma
        ("WK 1080/7", ["WK 1080/7"]),  # slash inside a MANN number is kept
        ("2044-3906 / 20443906", ["2044-3906"]),  # same number twice after normalizing
        ("A 000 420 15 20", ["A 000 420 15 20"]),  # original format preserved
        (" , ; ", []),
        ("", []),
        (None, []),
    ],
)
def test_split_numbers(raw, expected):
    assert split_numbers(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sku:FIT-BRK-00123", ("sku", "FIT-BRK-00123")),
        ("OE: 2044-3906", ("number", "2044-3906")),
        ("name：brake pad", ("text", "brake pad")),  # full-width colon
        ("brake pad", (None, "brake pad")),
        ("http://x", (None, "http://x")),  # unknown prefix is not a prefix
    ],
)
def test_split_query_prefix(raw, expected):
    assert split_query_prefix(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FIT-BRK-00123", "sku"),
        ("fit-brk-00123", "sku"),
        ("sku:whatever", "sku"),
        ("2044-3906", "number"),
        ("A 000 420 15 20", "number"),
        ("WG9100470107", "number"),
        ("oe:brake", "number"),  # explicit prefix wins
        ("brake pad volvo", "text"),
        ("FH12 brake pad", "text"),
        ("FH12", "text"),  # too short to be a part number
        ("name:20443906", "text"),
        ("刹车片", "text"),
        ("", "text"),
    ],
)
def test_detect_query_kind(raw, expected):
    assert detect_query_kind(raw, sku_prefix="FIT-") == expected


def test_detect_query_kind_reads_prefix_from_settings(settings):
    settings.COMPANY_SKU_PREFIX = "TP-"
    assert detect_query_kind("TP-00001") == "sku"
    assert detect_query_kind("FIT-BRK-00123") == "text"


@pytest.mark.parametrize(
    ("number", "brand"),
    [
        ("20443906", "Volvo"),
        ("7420443906", "Renault Trucks"),
        ("1746641", "Scania"),
        ("1387578", "DAF"),
        ("3924432", "Cummins"),
        ("A 000 420 15 20", "Mercedes-Benz"),
        ("81.50201-6229", "MAN"),
        ("500054655", "Iveco"),
        ("WG9100470107", "Sinotruk HOWO"),
        ("DZ9100410205", "Shacman"),
        ("612600061838", "Weichai"),
        ("K001234", "Knorr-Bremse"),
        ("9325000010", "WABCO"),
        ("0 986 424 813", "Bosch"),
        ("3400 700 526", "Sachs"),
        ("WK 1080/7", "MANN-FILTER"),
        ("FF5052", "Fleetguard"),
        ("P550425", "Donaldson"),
    ],
)
def test_brand_hint_includes_brand(number, brand):
    assert brand in brand_hint(number)


def test_brand_hint_returns_every_matching_brand():
    # Seven digits fit Scania, DAF and Cummins alike; hints rank, they never decide.
    assert set(brand_hint("1746641")) >= {"Scania", "DAF", "Cummins"}


@pytest.mark.parametrize("number", ["", None, "刹车片", "XYZ"])
def test_brand_hint_empty_when_nothing_fits(number):
    assert brand_hint(number) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("VOLVO", "Volvo"),
        ("Volvo Trucks", "Volvo"),
        ("沃尔沃", "Volvo"),
        ("Benz", "Mercedes-Benz"),
        ("MB", "Mercedes-Benz"),
        ("mercedes benz", "Mercedes-Benz"),
        ("M.A.N.", "MAN"),
        ("中国重汽", "Sinotruk HOWO"),
        ("Knorr Bremse", "Knorr-Bremse"),
        ("MANN+HUMMEL", "MANN-FILTER"),
        ("ＳＣＡＮＩＡ", "Scania"),  # full-width
        ("Unknown Motors", None),
        ("", None),
        (None, None),
    ],
)
def test_canonical_brand(raw, expected):
    assert canonical_brand(raw) == expected
