from decimal import Decimal

import pytest

from apps.importer.services import parsing


@pytest.mark.parametrize(
    ("text", "value", "currency"),
    [("USD 45.71", Decimal("45.71"), "USD"), ("$45.63", Decimal("45.63"), "USD"),
     ("18.5/pc", Decimal("18.5"), None), ("1,234.50", Decimal("1234.50"), None),
     ("¥128", Decimal("128"), "CNY"), ("128元", Decimal("128"), "CNY"),
     ("18,5", Decimal("18.5"), None), ("n/a", None, None), ("", None, None)],
)
def test_money(text, value, currency):
    assert parsing.parse_decimal(text) == value
    assert parsing.detect_currency(text) == currency


@pytest.mark.parametrize(("text", "value"), [("50pcs", 50), ("20 sets", 20), ("100", 100),
                                             ("MOQ: 200", 200), ("—", None)])
def test_int(text, value):
    assert parsing.parse_int(text) == value


@pytest.mark.parametrize(("text", "days"), [("25 days", 25), ("3-4 weeks", 28), ("2 months", 60),
                                            ("30", 30), ("15-20天", 20), ("ASAP", None)])
def test_lead_days(text, days):
    assert parsing.parse_lead_days(text) == days


@pytest.mark.parametrize(
    ("text", "expected"),
    [("20pcs/ctn", {"pcs_per_carton": 20, "unit": "pc"}),
     ("1 set/box", {"pcs_per_carton": 1, "unit": "set"}),
     ("2 pairs", {"pcs_per_carton": 2, "unit": "pair"}),
     ("39*32*15cm", {"carton_l_cm": 39.0, "carton_w_cm": 32.0, "carton_h_cm": 15.0}),
     ("450x300x250mm", {"carton_l_cm": 45.0, "carton_w_cm": 30.0, "carton_h_cm": 25.0}),
     ("5.4KGS", {"gross_weight_kg": 5.4}), ("500g", {"gross_weight_kg": 0.5}),
     ("4", {"pcs_per_carton": 4}), ("color box", {})],
)
def test_packing(text, expected):
    assert parsing.parse_packing(text) == expected


@pytest.mark.parametrize(("text", "years"), [("93-05", (1993, 2005)), ("1993~", (1993, None)),
                                             ("2005+", (2005, None)), ("1998-2004", (1998, 2004)),
                                             ("", (None, None))])
def test_years(text, years):
    assert parsing.parse_years(text) == years


@pytest.mark.parametrize(
    ("text", "vehicles"),
    [("Volvo FH12/FH16", [("Volvo", "FH12"), ("Volvo", "FH16")]),
     ("沃尔沃 FH", [("Volvo", "FH")]), ("Benz Actros", [("Mercedes-Benz", "Actros")]),
     ("M.A.N TGX", [("MAN", "TGX")]), ("中国重汽 豪沃", [("Sinotruk HOWO", "")]),
     ("Scania P/G/R", [("Scania", "P"), ("Scania", "G"), ("Scania", "R")]),
     ("Volvo Trucks FM", [("Volvo", "FM")]), ("Foton Auman", [("Foton Auman", "")]),
     ("", [])],
)
def test_vehicles(text, vehicles):
    assert parsing.parse_vehicles(text) == vehicles


@pytest.mark.parametrize(("text", "expected"), [("9.86E+08", True), ("1.2e5", True),
                                                ("20443906", False), ("E12345", False)])
def test_scientific_notation(text, expected):
    assert parsing.looks_scientific(text) is expected
