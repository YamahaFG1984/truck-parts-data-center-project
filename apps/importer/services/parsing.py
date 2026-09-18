"""Turn messy supplier cell text into typed values (docs/data-dictionary.html §10).

Pure functions; every one returns None (or an empty result) when it can't tell,
rather than guessing.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from apps.catalog.services.normalize import canonical_brand

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_CURRENCIES = [  # (pattern, code); first match wins
    (re.compile(r"us\$|usd|\$|美元|美金", re.I), "USD"),
    (re.compile(r"rmb|cny|¥|￥|元|人民币", re.I), "CNY"),
    (re.compile(r"eur|€", re.I), "EUR"),
]
_SCIENTIFIC = re.compile(r"^\s*\d+(?:\.\d+)?[eE][+-]?\d+\s*$")
_NUM = r"(\d+(?:\.\d+)?)"
_DIMENSIONS = re.compile(rf"{_NUM}\s*[x*×]\s*{_NUM}\s*[x*×]\s*{_NUM}\s*(mm|cm)?")
_PIECES = re.compile(r"(\d+)\s*(pcs|pc|sets?|pairs?|kits?)\b\s*(?:/|per)?\s*(ctn|carton|box|case)?")


def clean(text: str | None) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def looks_scientific(text: str | None) -> bool:
    """"9.86E+08": Excel turned a part number into a float; the digits are lost."""
    return bool(_SCIENTIFIC.match(clean(text)))


def parse_decimal(text: str | None) -> Decimal | None:
    """First number in the text: "USD 45.71" -> 45.71, "1,234.50" -> 1234.50."""
    match = _NUMBER.search(clean(text))
    if not match:
        return None
    raw = match.group()
    if "," in raw and "." in raw:  # 1,234.50
        raw = raw.replace(",", "")
    elif raw.count(",") == 1 and len(raw.split(",")[1]) != 3:  # 18,5 (decimal comma)
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_int(text: str | None) -> int | None:
    value = parse_decimal(text)
    return int(value) if value is not None else None


def detect_currency(*texts: str | None) -> str | None:
    for text in texts:
        for pattern, code in _CURRENCIES:
            if text and pattern.search(clean(text)):
                return code
    return None


def parse_lead_days(text: str | None) -> int | None:
    """"25 days" -> 25, "3-4 weeks" -> 28 (upper end), "2 months" -> 60, "30" -> 30."""
    text = clean(text).lower()
    numbers = [Decimal(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    upper = max(numbers)
    if re.search(r"week|wk|周", text):
        upper *= 7
    elif re.search(r"month|月", text):
        upper *= 30
    return int(upper)


def parse_packing(text: str | None) -> dict:
    """Packaging keys found in free text:
    "20pcs/ctn" -> pcs_per_carton + unit, "45*30*25cm" -> carton size,
    "5.4KGS" / "500g" -> gross weight."""
    text = clean(text).lower()
    result: dict = {}
    dims = _DIMENSIONS.search(text)
    if dims:
        factor = Decimal("0.1") if dims.group(4) == "mm" else Decimal(1)
        for key, value in zip(("carton_l_cm", "carton_w_cm", "carton_h_cm"), dims.groups()[:3],
                              strict=True):
            result[key] = float(Decimal(value) * factor)
    weight = re.search(r"(\d+(?:\.\d+)?)\s*(kgs?|g)\b", text)
    if weight:
        grams = weight.group(2) == "g"
        result["gross_weight_kg"] = float(Decimal(weight.group(1)) / (1000 if grams else 1))
    count = _PIECES.search(text)
    if count and not dims:
        result["pcs_per_carton"] = int(count.group(1))
        unit = count.group(2).rstrip("s")
        result["unit"] = {"pc": "pc", "set": "set", "pair": "pair", "kit": "kit"}.get(unit, "pc")
    elif not result and re.fullmatch(r"\d+", text):
        result["pcs_per_carton"] = int(text)
    return result


def parse_years(text: str | None) -> tuple[int | None, int | None]:
    """"93-05" -> (1993, 2005), "1993~" / "2005+" -> (from, None), "2010" -> (2010, None)."""
    years = [_full_year(y) for y in re.findall(r"\d{2,4}", clean(text))]
    if not years:
        return None, None
    if len(years) == 1:
        return years[0], None
    return years[0], years[1]


def _full_year(value: str) -> int:
    year = int(value)
    if year < 100:
        return 2000 + year if year <= 40 else 1900 + year
    return year


def parse_vehicles(text: str | None) -> list[tuple[str, str]]:
    """"Volvo FH12/FH16" -> [("Volvo", "FH12"), ("Volvo", "FH16")];
    "沃尔沃 FH" -> [("Volvo", "FH")]; "Scania P/G/R" -> three models.
    Unknown brands keep their spelling so nothing is lost."""
    text = clean(text)
    if not text:
        return []
    tokens = text.split()
    make, rest = None, ""
    for take in (2, 1):  # "Volvo Trucks FH" before "Volvo"
        if len(tokens) >= take and canonical_brand(" ".join(tokens[:take])):
            make = canonical_brand(" ".join(tokens[:take]))
            rest = " ".join(tokens[take:])
            break
    if make is None:
        return [(text, "")]
    if canonical_brand(rest) == make:  # "中国重汽 豪沃": the rest is the same brand
        rest = ""
    models = [m.strip() for m in rest.split("/") if m.strip()] or [""]
    return [(make, model) for model in models]
