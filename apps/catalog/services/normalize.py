"""Part number normalization: the single implementation used on write and on query.

Pure functions, no model imports. Rules follow docs/data-dictionary.html §9 and §10.
"""

import re
import unicodedata
from typing import Literal

QueryKind = Literal["sku", "number", "text"]

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")
# Separators that never occur inside a part number. "/" is handled separately
# because some numbers contain it (MANN "WK 1080/7").
_HARD_SEPARATORS = re.compile(r"[,;、|\n\r\t]+")
_MIN_NUMBER_LEN = 5
_PREFIXES: dict[str, QueryKind] = {"sku": "sku", "oe": "number", "name": "text"}


def normalize_number(raw: str | None) -> str:
    """Full-width to half-width, drop every non-alphanumeric character, upper-case.

    "A 000 420 15 20" -> "A0004201520", "81.50201-6229" -> "81502016229",
    "２０４４-3906" -> "20443906". Leading zeros are kept; non-Latin text becomes "".
    """
    if raw is None:
        return ""
    text = unicodedata.normalize("NFKC", str(raw))
    return _NON_ALNUM.sub("", text).upper()


def split_numbers(raw: str | None) -> list[str]:
    """Split a cell holding several numbers into the original-format pieces.

    Always splits on , ; 、 | and line breaks. Splits on "/" only when every side
    is long enough to be a full number, so "20443906/20568713" becomes two numbers
    while "WK 1080/7" stays one. Empty pieces and normalized duplicates are dropped.
    """
    if raw is None:
        return []
    text = unicodedata.normalize("NFKC", str(raw))
    pieces: list[str] = []
    for chunk in _HARD_SEPARATORS.split(text):
        parts = chunk.split("/")
        if len(parts) > 1 and all(len(normalize_number(p)) >= _MIN_NUMBER_LEN for p in parts):
            pieces.extend(parts)
        else:
            pieces.append(chunk)

    result: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        piece = piece.strip()
        norm = normalize_number(piece)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(piece)
    return result


def split_query_prefix(raw: str | None) -> tuple[QueryKind | None, str]:
    """Return (explicit kind, remaining text) for "sku:", "oe:" or "name:" prefixes."""
    text = unicodedata.normalize("NFKC", raw or "").strip()
    head, sep, rest = text.partition(":")
    if sep and head.strip().lower() in _PREFIXES:
        return _PREFIXES[head.strip().lower()], rest.strip()
    return None, text


def detect_query_kind(raw: str | None, sku_prefix: str | None = None) -> QueryKind:
    """Guess what a search box input is.

    Explicit prefix wins. Otherwise: starts with the company SKU prefix -> "sku";
    normalized length >= 5 with digits and fewer letters than half -> "number";
    anything else -> "text".
    """
    explicit, text = split_query_prefix(raw)
    if explicit:
        return explicit

    norm = normalize_number(text)
    if not norm or not any(ch.isdigit() for ch in norm):
        return "text"

    if sku_prefix is None:
        from django.conf import settings

        sku_prefix = settings.COMPANY_SKU_PREFIX
    prefix_norm = normalize_number(sku_prefix)
    if prefix_norm and norm.startswith(prefix_norm):
        return "sku"

    letters = sum(ch.isalpha() for ch in norm)
    if len(norm) >= _MIN_NUMBER_LEN and letters / len(norm) < 0.5:
        return "number"
    return "text"


# Brand format heuristics from docs/data-dictionary.html §9. They only rank
# candidates; several brands share a format, so a number can match many.
_BRAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (brand, re.compile(pattern))
    for brand, pattern in [
        ("Volvo", r"^\d{8}$"),
        ("Renault Trucks", r"^(50|74)\d{8}$"),
        ("Scania", r"^\d{7}$"),
        ("DAF", r"^\d{7}$"),
        ("Cummins", r"^\d{7}$"),
        ("Mercedes-Benz", r"^[ANQ]\d{10}$"),
        ("MAN", r"^(81|51)\d{9}$"),
        ("Iveco", r"^\d{8,9}$"),
        ("Sinotruk HOWO", r"^(WG|VG|AZ)\d{10}$"),
        ("Shacman", r"^DZ\d{10}$"),
        ("Weichai", r"^61\d{10}$"),
        ("Knorr-Bremse", r"^(K\d{6}|II\d{5}[A-Z])$"),
        ("WABCO", r"^\d{10}$"),
        ("Bosch", r"^0\d{9}$"),
        ("Sachs", r"^\d{10}$"),
        ("MANN-FILTER", r"^(W|WK|WDK|C|CU|CF|H|HU|PU)\d{3,}[A-Z0-9]*$"),
        ("Fleetguard", r"^(FF|LF|AF|FS|WF|HF)\d{4,5}$"),
        ("Donaldson", r"^P\d{6}$"),
    ]
]


def brand_hint(number: str | None) -> list[str]:
    """Brands whose numbering format fits; used for ranking only, never filtering."""
    norm = normalize_number(number)
    if not norm:
        return []
    return [brand for brand, pattern in _BRAND_PATTERNS if pattern.match(norm)]


BRAND_ALIASES: dict[str, list[str]] = {
    "Volvo": ["volvo", "volvo trucks", "volvo truck", "沃尔沃"],
    "Renault Trucks": ["renault", "renault trucks", "rvi", "雷诺"],
    "Scania": ["scania", "斯堪尼亚"],
    "Mercedes-Benz": ["mercedes", "mercedes-benz", "benz", "mb", "daimler", "奔驰"],
    "MAN": ["man", "man trucks", "man truck", "曼"],
    "DAF": ["daf", "达夫"],
    "Iveco": ["iveco", "依维柯"],
    "Cummins": ["cummins", "康明斯"],
    "Sinotruk HOWO": ["sinotruk", "howo", "sinotruk howo", "cnhtc", "中国重汽", "重汽", "豪沃"],
    "Shacman": ["shacman", "shaanxi", "陕汽", "陕西重汽"],
    "FAW": ["faw", "jiefang", "一汽", "解放"],
    "Dongfeng": ["dongfeng", "东风"],
    "Weichai": ["weichai", "潍柴"],
    "Freightliner": ["freightliner"],
    "Kenworth": ["kenworth"],
    "Peterbilt": ["peterbilt"],
    "International": ["international", "navistar"],
    "Knorr-Bremse": ["knorr", "knorr-bremse", "knorr bremse", "克诺尔"],
    "WABCO": ["wabco", "威伯科"],
    "Bosch": ["bosch", "博世"],
    "MANN-FILTER": ["mann", "mann-filter", "mann filter", "mann+hummel", "曼牌"],
    "Fleetguard": ["fleetguard", "弗列加"],
    "Donaldson": ["donaldson", "唐纳森"],
    "Sachs": ["sachs", "zf sachs", "zf-sachs", "萨克斯"],
}


def _brand_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s\-_.·/&+]+", "", text)


_ALIAS_INDEX: dict[str, str] = {
    _brand_key(alias): canonical
    for canonical, aliases in BRAND_ALIASES.items()
    for alias in [canonical, *aliases]
}


def canonical_brand(raw: str | None) -> str | None:
    """Map a brand spelling ("VOLVO", "沃尔沃", "Benz") to its canonical name.

    Returns None for unknown brands so the caller can keep the original and flag it.
    """
    if not raw:
        return None
    return _ALIAS_INDEX.get(_brand_key(raw))
