"""What the review pages show: open items grouped into clusters, and a side-by-side
view of two records where every value carries its source (read-only)."""

from collections import defaultdict

from ..models import ReviewItem

ORDER = {"strong": 0, "conflict": 1, "medium": 2, "weak": 3, "info": 4}
# (field, label) rows of the side-by-side view, in reading order.
ROWS = [("part_type", "品类"), ("position", "位置"), ("fitment", "适配"), ("dims", "尺寸 cm"),
        ("oe_numbers", "OE / 互换号"), ("supplier_sku", "供应商料号"), ("name", "名称原文"),
        ("price", "单价"), ("currency", "币种"), ("moq", "MOQ"), ("quote_date", "报价日期")]


def open_items(category="", strength="", supplier=""):
    items = (ReviewItem.objects.filter(status=ReviewItem.Status.OPEN)
             .select_related("record_a__supplier", "record_b__supplier",
                             "record_a__source_file", "record_b__source_file"))
    if category:
        items = items.filter(category=category)
    if strength:
        items = items.filter(strength=strength)
    if supplier.isdigit():
        items = [i for i in items if int(supplier) in (i.record_a.supplier_id,
                                                       getattr(i.record_b, "supplier_id", None))]
    return list(items)


def clusters(items) -> tuple[list[dict], list[ReviewItem]]:
    """Pair items joined wherever they share a record, so one person can settle a whole
    group at once; conflicts stand alone; single-record items are returned separately."""
    pairs = [i for i in items if i.kind == ReviewItem.Kind.PAIR]
    parent = {}

    def root(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Conflicts ask "are these really different?" and would chain unrelated groups
    # (all left grilles to all right ones), so they never join clusters: each is its own.
    for item in pairs:
        if item.strength != "conflict":
            parent[root(item.identity_a)] = root(item.identity_b)
    groups = defaultdict(list)
    for item in pairs:
        key = ("conflict", item.pk) if item.strength == "conflict" else root(item.identity_a)
        groups[key].append(item)
    result = []
    for group in groups.values():
        group.sort(key=lambda i: (ORDER.get(i.strength, 9), i.pk))
        records = {}
        for item in group:
            records.setdefault(item.identity_a, item.record_a)
            records.setdefault(item.identity_b, item.record_b)
        result.append({"items": group, "records": sorted(records.values(), key=_record_order),
                       "strength": group[0].strength,
                       "has_conflict": any(i.strength == "conflict" for i in group)})
    result.sort(key=lambda c: (ORDER.get(c["strength"], 9), -len(c["records"])))
    singles = [i for i in items if i.kind != ReviewItem.Kind.PAIR]
    return result, singles


def side_by_side(item: ReviewItem) -> list[dict]:
    """[{label, a: {text, source, flag}, b: ...}] with flag "conflict" or "missing"."""
    conflicts = {c["field"] for c in item.conflicts}
    missing = {(m["field"], m["side"]) for m in item.missing}
    rows = []
    for name, label in ROWS:
        row = {"label": label}
        for side, record in (("a", item.record_a), ("b", item.record_b)):
            if record is None:
                continue
            flag = ("conflict" if name in conflicts else
                    "missing" if (name, side) in missing or (name, "both") in missing else "")
            row[side] = cell(record, name) | {"flag": flag}
        rows.append(row)
    return rows


def cell(record, name) -> dict:
    entry = record.fields.get(name, {})
    value = entry.get("value")
    sources = entry.get("sources", [])
    where = "；".join(f"{s['column']} · {s['cell']}" for s in sources)
    raw = "；".join(s["raw"] for s in sources)
    return {"text": _text(name, value), "source": where, "raw": raw,
            "warnings": entry.get("warnings", [])}


def _text(name, value) -> str:
    if value in (None, "", []):
        return ""
    if name == "fitment":
        return "；".join(f"{f['make']} {f['model']}"
                        + (f" {f['year_from']}–{f['year_to'] or '至今'}" if f["year_from"] else "")
                        for f in value)
    if name == "dims":
        return " × ".join(str(v).rstrip("0").rstrip(".") for v in value)
    if isinstance(value, list):
        return "、".join(str(v) for v in value)
    return str(value)


def _record_order(record):
    return (record.supplier.name, record.record_key)
