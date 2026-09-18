"""Completeness score (docs/architecture.html §7.3).

One 0-100 number per part saying how much of the key data is present, plus the
list of what is missing. recompute() works in a fixed number of queries: one
SELECT with Exists() annotations and one UPDATE per 500 changed rows.
"""

from dataclasses import dataclass, field

from django.db.models import Avg, Count, Q, QuerySet

from ..managers import MISSING_FILTERS, has_related
from ..models import Part, PartNumber

# item -> weight. Keys match MISSING_FILTERS where a SQL check exists.
WEIGHTS = {
    "name": 10,  # name_en present, at least 5 characters
    "category": 10,
    "oe": 20,  # at least one OE number
    "cross": 10,  # at least one cross reference
    "fitment": 10,
    "image": 15,  # a primary image
    "attributes": 10,  # every value the category schema marks required
    "packaging": 5,  # pcs_per_carton and gross weight
    "offer": 10,  # at least one supplier quote
}
# Labels for the dashboard and part list filters (keys of MISSING_FILTERS).
MISSING_LABELS = {
    "name": "缺英文品名",
    "category": "缺分类",
    "oe": "缺 OE 号",
    "cross": "缺互换号",
    "fitment": "缺适配车型",
    "image": "缺主图",
    "description": "缺英文描述",
    "packaging": "缺包装信息",
    "offer": "缺供应商报价",
}
# (label, low, high), both ends inclusive, so a list filtered by ?score=low-high
# shows exactly the parts counted in the bucket.
BUCKETS = [("0–39", 0, 39), ("40–69", 40, 69), ("70–89", 70, 89), ("90–100", 90, 100)]
BATCH_SIZE = 500
_FLAGS = {
    "_has_oe": lambda: has_related("PartNumber", kind="OE"),
    "_has_cross": lambda: has_related("PartNumber", kind="CROSS"),
    "_has_fitment": lambda: has_related("Fitment"),
    "_has_image": lambda: has_related("PartImage", is_primary=True),
    "_has_offer": lambda: has_related("suppliers.SupplierOffer"),
}


@dataclass
class QualityReport:
    score: int
    missing: list[str] = field(default_factory=list)


def with_quality_flags(qs: QuerySet[Part]) -> QuerySet[Part]:
    """Everything evaluate() needs, in one query."""
    return qs.select_related("category").annotate(**{k: f() for k, f in _FLAGS.items()})


def evaluate(part: Part) -> QualityReport:
    """Score one part. Uses annotations from with_quality_flags() when present,
    otherwise fetches them for this part (one query)."""
    if not hasattr(part, "_has_oe"):
        part = with_quality_flags(Part.objects.filter(pk=part.pk)).get()

    present = {
        "name": len((part.name_en or "").strip()) >= 5,
        "category": part.category_id is not None,
        "oe": part._has_oe,
        "cross": part._has_cross,
        "fitment": part._has_fitment,
        "image": part._has_image,
        "attributes": _required_attributes_present(part),
        "packaging": bool(
            (part.packaging or {}).get("pcs_per_carton")
            and (part.packaging or {}).get("gross_weight_kg")
        ),
        "offer": part._has_offer,
    }
    missing = [item for item in WEIGHTS if not present[item]]
    return QualityReport(score=100 - sum(WEIGHTS[m] for m in missing), missing=missing)


def _required_attributes_present(part: Part) -> bool:
    if part.category_id is None:
        return False  # nothing to check against; the category item already says why
    values = part.attributes or {}
    return all(values.get(key) is not None for key in part.category.schema.required_keys)


def recompute(parts: QuerySet[Part] | None = None) -> int:
    """Rewrite completeness_score for the given parts (default: all). Returns how many
    scores changed."""
    qs = with_quality_flags(parts if parts is not None else Part.objects.all())
    changed = []
    for part in qs.order_by("pk"):
        score = evaluate(part).score
        if part.completeness_score != score:
            part.completeness_score = score
            changed.append(part)
    Part.objects.bulk_update(changed, ["completeness_score"], batch_size=BATCH_SIZE)
    return len(changed)


def summary() -> dict:
    """Dashboard numbers in one aggregate query, plus the duplicate group count."""
    aggregates = {"total": Count("pk"), "average": Avg("completeness_score")}
    aggregates |= {
        f"bucket_{i}": Count("pk", filter=Q(completeness_score__gte=lo, completeness_score__lte=hi))
        for i, (_, lo, hi) in enumerate(BUCKETS)
    }
    aggregates |= {
        f"missing_{key}": Count("pk", filter=cond()) for key, cond in MISSING_FILTERS.items()
    }
    row = Part.objects.aggregate(**aggregates)
    return {
        "total": row["total"],
        "average": round(row["average"] or 0),
        "complete_share": (
            round(100 * row[f"bucket_{len(BUCKETS) - 1}"] / row["total"]) if row["total"] else 0
        ),
        "distribution": [
            {"label": label, "count": row[f"bucket_{i}"], "low": lo, "high": hi}
            for i, (label, lo, hi) in enumerate(BUCKETS)
        ],
        "missing": {k: row[f"missing_{k}"] for k in MISSING_FILTERS},
        "duplicate_groups": len(_duplicate_norms()),
    }


def _duplicate_norms() -> list[str]:
    return list(
        PartNumber.objects.filter(kind__in=["OE", "CROSS"])
        .values("number_norm")
        .annotate(parts=Count("part", distinct=True))
        .filter(parts__gt=1)
        .order_by("number_norm")
        .values_list("number_norm", flat=True)
    )


def duplicates() -> list[tuple[str, list[Part]]]:
    """Suspected duplicates: an OE or cross number on more than one part.

    Some are true duplicates to merge, some are genuine alternatives; a person
    decides. Two queries regardless of how many groups there are.
    """
    norms = _duplicate_norms()
    groups: dict[str, dict[int, Part]] = {n: {} for n in norms}
    rows = PartNumber.objects.filter(number_norm__in=norms, kind__in=["OE", "CROSS"])
    for pn in rows.select_related("part").order_by("part__sku"):
        groups[pn.number_norm].setdefault(pn.part_id, pn.part)
    return [(norm, list(parts.values())) for norm, parts in groups.items()]
