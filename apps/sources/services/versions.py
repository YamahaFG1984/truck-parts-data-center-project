"""Compare a record with the supplier's previous version of it (docs/archive-design.html §10).

Key fields decide what a product is; changing one needs a person. Quote fields change
all the time; other fields (wording, notes) are informative. Old versions are never
touched: a change is a new version pointing at the previous one.
"""

from apps.catalog.services.normalize import normalize_number

# (field, label), in display order.
KEY_FIELDS = [("part_type", "品类"), ("position", "位置"), ("make", "适配品牌"),
              ("model", "适配车型"), ("years", "适配年份"), ("dims", "尺寸 cm"),
              ("oe_numbers", "OE 号")]
QUOTE_FIELDS = [("price", "单价"), ("currency", "币种"), ("moq", "MOQ"), ("quote_date", "报价日期")]
OTHER_FIELDS = [("name", "名称原文"), ("supplier_sku", "供应商料号")]


def snapshot_record(record) -> dict:
    return _snapshot(
        {f: getattr(record, f) for f in ("part_type", "position", "make", "model", "year_from",
                                         "year_to", "dim_l_cm", "dim_w_cm", "dim_h_cm", "price",
                                         "currency", "moq", "quote_date", "name",
                                         "supplier_sku")},
        [n.number for n in record.numbers.all() if n.kind == "oe"])


def snapshot_standardized(std) -> dict:
    return _snapshot(std.typed, [n for kind, n in std.numbers if kind == "oe"])


def diff(old: dict, new: dict) -> tuple[str, list[dict]]:
    """(change, [{field, label, old, new, kind}]) where change is key_change,
    price_update, info_update or "" when nothing comparable changed."""
    changes = []
    for kind, fields in (("key", KEY_FIELDS), ("quote", QUOTE_FIELDS), ("other", OTHER_FIELDS)):
        for name, label in fields:
            if old[name] != new[name]:
                changes.append({"field": name, "label": label, "kind": kind,
                                "old": _show(old[name]), "new": _show(new[name])})
    kinds = {c["kind"] for c in changes}
    change = ("key_change" if "key" in kinds else "price_update" if kinds == {"quote"} else
              "info_update" if kinds else "")
    return change, changes


def summary(changes: list[dict]) -> str:
    return "；".join(f"{c['label']} {c['old'] or '（空）'} → {c['new'] or '（空）'}"
                    for c in changes)


def _snapshot(typed: dict, oe_numbers) -> dict:
    dims = (typed["dim_l_cm"], typed["dim_w_cm"], typed["dim_h_cm"])
    return {
        "part_type": typed["part_type"], "position": typed["position"],
        "make": typed["make"], "model": typed["model"],
        "years": (typed["year_from"], typed["year_to"]),
        "dims": tuple(sorted(dims)) if all(d is not None for d in dims) else None,
        "oe_numbers": tuple(sorted({normalize_number(n) for n in oe_numbers} - {""})),
        "price": typed["price"], "currency": typed["currency"], "moq": typed["moq"],
        "quote_date": typed["quote_date"], "name": typed["name"],
        "supplier_sku": typed["supplier_sku"],
    }


def _show(value) -> str:
    if value in (None, "", ()):
        return ""
    if isinstance(value, tuple):
        if len(value) == 2 and all(v is None or isinstance(v, int) for v in value):
            return f"{value[0] or ''}–{value[1] or ''}".strip("–") or ""
        return " × ".join(f"{v.normalize():f}" if hasattr(v, "normalize") else str(v)
                          for v in value)
    if hasattr(value, "normalize"):
        return f"{value.normalize():f}"
    return str(value)
