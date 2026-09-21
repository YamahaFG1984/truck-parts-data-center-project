"""Field standardization with lineage (docs/archive-design.html §7).

Every standard field records where it came from (column, cell, raw text), the rule
that read it and any warning. Nothing is filled in by assumption: a price without
a currency stays without a currency, a size without a unit is not converted.
"""

import datetime as dt
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from apps.catalog.services.normalize import canonical_brand, split_numbers
from apps.importer.services.parsing import parse_decimal

from .mapping import FIELDS
from .readers import Row

VOCABULARY = Path(__file__).resolve().parent.parent / "rules" / "vocabulary.json"
# Short labels for warnings and "missing" badges (column-picker labels are longer).
LABELS = FIELDS | {"part_type": "品类", "years": "适配年份", "fitment": "适配车型",
                   "dims": "尺寸", "oe_numbers": "OE 号"}
# Fields whose absence makes a record "to be completed", in display order. Model years
# are not among them: many catalogs never state them; M25 compares them per pair.
KEY_FIELDS = ["part_type", "position", "fitment", "oe_numbers", "dims", "price", "currency",
              "moq", "quote_date"]
CURRENCY_SYMBOLS = {"$": {"USD", "CAD", "AUD", "MXN", "NZD", "HKD", "SGD"}, "€": {"EUR"},
                    "£": {"GBP"}, "¥": {"CNY", "JPY"}}
CURRENCY_WORDS = {"US$": "USD", "RMB": "CNY", "YUAN": "CNY", "EURO": "EUR", "EUROS": "EUR"}
_YEARS = re.compile(r"\b((?:19|20)\d{2})\b\s*(?:(?:-|–|—|~|to)\s*(?:((?:19|20)\d{2})\b|"
                    r"(present|current|up|on)\b)|(\+))?", re.I)
_DIMS = re.compile(r"(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)"
                   r"\s*(cm|mm|m|inches|inch|in|\")?", re.I)
_UNIT_IN_HEADER = re.compile(r"\b(cm|mm|inches|inch|in)\b", re.I)
CENT = Decimal("0.01")
# How suppliers write "nothing here"; such cells count as empty.
BLANKS = {"-", "--", "—", "/", "n/a", "na", "none", "null", "tbd"}


@cache
def vocabulary() -> dict:
    data = json.loads(VOCABULARY.read_text(encoding="utf-8"))

    def by_length(groups):  # [(alias, canonical)], longest alias first
        return sorted(((_words(a), c) for c, aliases in groups for a in aliases),
                      key=lambda pair: -len(pair[0]))

    data["_types"] = by_length((c, v["aliases"] + [c]) for c, v in data["part_types"].items())
    data["_name_positions"] = by_length(data["name_positions"].items())
    in_column = {c: [c, *a] for c, a in data["name_positions"].items()}
    for canonical, aliases in data["column_positions"].items():  # add to, never replace
        in_column.setdefault(canonical, [canonical]).extend(aliases)
    data["_column_positions"] = by_length(in_column.items())
    data["_makes"] = by_length((c, [c, *a]) for c, a in data["makes"].items())
    return data


@dataclass
class Standardized:
    fields: dict = field(default_factory=dict)  # field -> value, rule, warnings, sources
    typed: dict = field(default_factory=dict)  # SourceRecord column -> value
    numbers: list = field(default_factory=list)  # (RecordNumber kind, number)
    warnings: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    content_hash: str = ""

    def put(self, name, value, cells, rule, warnings=()):
        self.fields[name] = {
            "value": value, "rule": rule, "warnings": list(warnings),
            "sources": [{"column": h, "cell": c.coord, "raw": c.text} for h, c in cells],
        }
        self.warnings += [f"{LABELS.get(name, name)}：{w}" for w in warnings]

    def value(self, name, default=None):
        return self.fields.get(name, {}).get("value", default)


def standardize(row: Row, columns: list[dict]) -> Standardized:
    """Apply a confirmed column mapping to one row."""
    cells: dict[str, list] = {}
    for column in columns:
        cell = row.cells.get(column["header"])
        if (column["field"] != "ignore" and cell is not None and cell.text
                and cell.text.casefold() not in BLANKS):
            cells.setdefault(column["field"], []).append((column["header"], cell))

    out = Standardized()
    for name in ("record_id", "supplier_sku", "brand", "name", "category", "note"):
        if name in cells:
            out.put(name, "; ".join(c.text for _, c in cells[name]), cells[name], "text")
    if "spec" in cells:
        out.put("spec", {h: c.text for h, c in cells["spec"]}, cells["spec"], "text")
    _numbers(out, cells)
    _type_and_position(out, cells)
    _fitment(out, cells)
    _dims(out, cells)
    _price_and_currency(out, cells)
    _moq(out, cells)
    _quote_date(out, cells)

    out.typed = _typed(out)
    sided = vocabulary()["part_types"].get(out.value("part_type"), {}).get("sided", False)
    for name in KEY_FIELDS:
        if name == "position" and not sided:
            continue
        if out.value(name) in (None, "", []):
            out.missing.append(name)
    raw = {n: [c.text for _, c in cs] for n, cs in sorted(cells.items())}
    out.content_hash = hashlib.sha256(json.dumps(raw, ensure_ascii=False).encode()).hexdigest()
    return out


# --- fields ------------------------------------------------------------------------


def _numbers(out, cells):
    if "record_id" in cells:
        out.numbers.append(("source_id", out.value("record_id")))
    if "supplier_sku" in cells:
        out.numbers.append(("supplier_sku", out.value("supplier_sku")))
    if "oe_numbers" in cells:
        numbers = [n for _, c in cells["oe_numbers"] for n in split_numbers(c.text)]
        out.put("oe_numbers", numbers, cells["oe_numbers"], "split_numbers")
        out.numbers += [("oe", n) for n in numbers]


def _type_and_position(out, cells):
    vocab = vocabulary()
    name_cells = cells.get("name", [])
    name = name_cells[0][1].text if name_cells else ""
    part_type, rest = _find(name, vocab["_types"])
    type_cells, rule, warnings = name_cells, "vocabulary", []
    if not part_type and "category" in cells:
        part_type, _ = _find(cells["category"][0][1].text, vocab["_types"])
        type_cells = cells["category"]
    if not part_type and name:
        _, stripped = _find(name, vocab["_name_positions"], remove_all=True)
        part_type, rule = stripped.strip().title(), "unregistered"
        warnings.append(f"“{part_type}”不在品类词表中，按原名参与比对；可补充词表后重跑")
    if part_type:
        out.put("part_type", part_type, type_cells, rule, warnings)

    from_name, _ = _find(rest if part_type and rule == "vocabulary" else name,
                         vocab["_name_positions"])
    column_cells = cells.get("position", [])
    if column_cells:
        text = column_cells[0][1].text
        position, left = _find(text, vocab["_column_positions"])
        warnings = []
        if not position or left.strip():
            position = text
            warnings.append(f"无法识别的位置“{text}”，保留原文")
        elif from_name and from_name != position:
            warnings.append(f"名称中是 {from_name}，位置列是 {position}，以位置列为准")
        out.put("position", position, column_cells, "position_column", warnings)
    elif from_name:
        out.put("position", from_name, name_cells, "from_name")


def _fitment(out, cells):
    entries, source, warnings = [], [], []
    if "fitment" in cells:
        source = cells["fitment"]
        for part in re.split(r"[;\n]+", source[0][1].text):
            if part.strip():
                entry, entry_warnings = _parse_fitment(part)
                entries.append(entry)
                warnings += entry_warnings
    elif {"make", "model", "years"} & cells.keys():
        source = [c for n in ("make", "model", "years") for c in cells.get(n, [])]
        text = " ".join(cells[n][0][1].text for n in ("make", "model", "years") if n in cells)
        entry, warnings = _parse_fitment(text)
        entries.append(entry)
    if not entries:
        return
    if len(entries) > 1:
        warnings.append(f"有 {len(entries)} 条适配，比对时只用第一条")
    first = entries[0]
    if first["year_from"] is None:
        warnings.append("未注明年份")
    out.put("fitment", entries, source, "fitment", warnings)
    if first["year_from"] is not None:
        out.put("years", [first["year_from"], first["year_to"]], source, "fitment")


def _parse_fitment(text: str) -> tuple[dict, list[str]]:
    warnings = []
    years = _YEARS.search(text)
    year_from = year_to = None
    if years:
        year_from = int(years.group(1))
        if years.group(2):
            year_to = int(years.group(2))
        elif not (years.group(3) or years.group(4)):
            year_to = year_from  # a single model year
        text = text[:years.start()] + text[years.end():]
    make, rest = _find(text, vocabulary()["_makes"], at_start=True)
    if make:  # keep the supplier's casing for the model: drop only the make's words
        rest = " ".join(text.split()[len(_words(_make_alias(make, text)).split()):])
    else:
        tokens = text.split()
        make = canonical_brand(tokens[0]) if tokens else None
        rest = " ".join(tokens[1:]) if make else text
        if not make and tokens:
            make, rest = tokens[0], " ".join(tokens[1:])
            warnings.append(f"“{make}”不在整车品牌词表中")
    model = " ".join(rest.replace(",", " ").split())
    if not model:
        warnings.append("缺车型")
    return {"make": make or "", "model": model, "year_from": year_from,
            "year_to": year_to}, warnings


def _dims(out, cells):
    if "dims" not in cells:
        return
    header, cell = cells["dims"][0]
    match = _DIMS.search(cell.text)
    if not match:
        out.put("dims", None, cells["dims"], "dims_lxwxh", [f"无法解析尺寸“{cell.text}”"])
        return
    unit = (match.group(4) or "").lower()
    if not unit:
        in_header = _UNIT_IN_HEADER.search(header)
        unit = in_header.group(1).lower() if in_header else ""
    numbers = [Decimal(n.replace(",", ".")) for n in match.groups()[:3]]
    factor = vocabulary()["dim_units_to_cm"].get(unit)
    if factor is None:
        out.put("dims", None, cells["dims"], "dims_lxwxh",
                [f"尺寸“{cell.text}”没有单位，未换算"])
        return
    value = [str((n * Decimal(str(factor))).quantize(CENT)) for n in numbers]
    out.put("dims", value, cells["dims"], f"dims_lxwxh_{unit}_to_cm")


def _price_and_currency(out, cells):
    price_cell = cells["price"][0][1] if "price" in cells else None
    amount, symbol_in_text, warnings = None, None, []
    if price_cell:
        if isinstance(price_cell.value, (int, float)) and not isinstance(price_cell.value, bool):
            amount = Decimal(price_cell.text)
        else:
            amount = parse_decimal(price_cell.text)
            symbol_in_text = _currency_code(price_cell.text, loose=True)
        if amount is None:
            warnings.append(f"无法读出价格“{price_cell.text}”")

    code, rule, currency_warnings = None, "currency_column", []
    if "currency" in cells:
        text = cells["currency"][0][1].text
        code = _currency_code(text)
        if text.strip() == "$":
            code = "USD"
            currency_warnings.append("币种写的是“$”，按 USD 处理；如是加元等请人工更正")
        elif code is None:
            currency_warnings.append(f"无法识别的币种“{text}”")
    elif symbol_in_text:
        code, rule = symbol_in_text, "price_text"

    shown = _format_symbol(price_cell.number_format) if price_cell else None
    if shown and code and not _symbol_matches(shown, code):
        warnings.append(f"单元格格式显示 {shown}，与币种 {code} 不一致，以币种为准")
    elif shown and not code and "currency" not in cells:
        warnings.append(f"单元格格式带 {shown}，但没有币种列，不据此认定币种")

    if price_cell:
        out.put("price", str(amount) if amount is not None else None, cells["price"],
                "number", warnings)
    if "currency" in cells or code:
        out.put("currency", code, cells.get("currency") or cells["price"], rule,
                currency_warnings)


def _moq(out, cells):
    if "moq" not in cells:
        return
    cell = cells["moq"][0][1]
    number = parse_decimal(cell.text)
    warnings = []
    if number is None or number != number.to_integral_value():
        warnings.append(f"无法读出整数起订量“{cell.text}”")
        number = None
    out.put("moq", int(number) if number is not None else None, cells["moq"], "integer",
            warnings)


def _quote_date(out, cells):
    if "quote_date" not in cells:
        return
    cell = cells["quote_date"][0][1]
    if isinstance(cell.value, dt.datetime):
        value, warnings = cell.value.date(), []
    elif isinstance(cell.value, dt.date):
        value, warnings = cell.value, []
    else:
        value, warnings = _parse_date(cell.text)
    out.put("quote_date", value.isoformat() if value else None, cells["quote_date"], "date",
            warnings)


# --- helpers -----------------------------------------------------------------------


def _words(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " " + " ".join(re.sub(r"[^a-z0-9/&\"]+", " ", text).split()) + " "


def _find(text, table, *, at_start=False, remove_all=False):
    """(canonical, rest of text) for the longest alias found as whole words."""
    haystack, found = _words(text or ""), None
    for alias, canonical in table:
        index = haystack.find(alias)
        if index < 0 or (at_start and index != 0):
            continue
        found = found or canonical
        haystack = haystack[:index] + " " + haystack[index + len(alias):]
        if not remove_all:
            break
    return found, haystack


def _make_alias(make: str, text: str) -> str:
    """The alias of `make` that `text` starts with ("Volvo Trucks VNL" -> "volvo trucks")."""
    haystack = _words(text)
    return next(a for a, c in vocabulary()["_makes"] if c == make and haystack.startswith(a))


def _currency_code(text: str, *, loose=False) -> str | None:
    clean = unicodedata.normalize("NFKC", text or "").strip().upper()
    if clean in CURRENCY_WORDS:
        return CURRENCY_WORDS[clean]
    if re.fullmatch(r"[A-Z]{3}", clean):
        return clean
    for word, code in CURRENCY_WORDS.items():
        if loose and word in clean:
            return code
    codes = re.findall(r"\b(USD|EUR|GBP|CNY|CAD|JPY|MXN|AUD)\b", clean) if loose else []
    if codes:
        return codes[0]
    symbols = [s for s in CURRENCY_SYMBOLS if s in clean]
    # € and £ name one currency; $ and ¥ do not, so they are never read as a code.
    if len(symbols) == 1 and len(CURRENCY_SYMBOLS[symbols[0]]) == 1:
        return next(iter(CURRENCY_SYMBOLS[symbols[0]]))
    return None


def _format_symbol(number_format: str) -> str | None:
    """The currency an Excel number format displays: "$#,##0.00" -> "$"."""
    bracket = re.search(r"\[\$([^\]-]+)", number_format or "")
    shown = bracket.group(1) if bracket else number_format or ""
    for symbol in ("€", "£", "¥", "$"):
        if symbol in shown:
            return symbol
    code = re.search(r"\b(USD|EUR|GBP|CNY|CAD|JPY)\b", shown.upper())
    return code.group(1) if code else None


def _symbol_matches(shown: str, code: str) -> bool:
    return code in CURRENCY_SYMBOLS.get(shown, {shown})


def _parse_date(text: str) -> tuple[dt.date | None, list[str]]:
    text = text.strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%b %d, %Y", "%d %b %Y",
                    "%B %d, %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(text, pattern).date(), []
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
    if match:
        a, b, year = (int(g) for g in match.groups())
        if a > 12 >= b:
            return dt.date(year, b, a), []
        if b > 12 >= a:
            return dt.date(year, a, b), []
        return None, [f"日期“{text}”无法确定日月顺序，保留原文"]
    return None, [f"无法识别的日期“{text}”"]


def _typed(out: Standardized) -> dict:
    fitment = (out.value("fitment") or [{}])[0]
    dims = out.value("dims") or [None, None, None]
    return {
        "supplier_sku": (out.value("supplier_sku") or "")[:100],
        "name": (out.value("name") or "")[:300],
        "part_type": (out.value("part_type") or "")[:100],
        "position": (out.value("position") or "")[:20],
        "make": (fitment.get("make") or "")[:60],
        "model": (fitment.get("model") or "")[:100],
        "year_from": fitment.get("year_from"),
        "year_to": fitment.get("year_to"),
        "dim_l_cm": _decimal(dims[0]), "dim_w_cm": _decimal(dims[1]),
        "dim_h_cm": _decimal(dims[2]),
        "price": _decimal(out.value("price")),
        "currency": out.value("currency") or "",
        "moq": out.value("moq"),
        "quote_date": dt.date.fromisoformat(out.value("quote_date"))
        if out.value("quote_date") else None,
    }


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None
