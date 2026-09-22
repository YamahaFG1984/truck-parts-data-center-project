"""Candidate pairs and their evidence (docs/archive-design.html §8, figure R3).

Matching never merges anything. It finds pairs of current source records worth a
person's attention, decides which category each pair falls into, and writes the
evidence (why it came up, what agrees, what conflicts, what is missing, what to do)
as ReviewItems. Records missing key fields get an item of their own.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache
from itertools import combinations
from pathlib import Path

from django.db import transaction

from apps.sources.models import SourceRecord
from apps.sources.services.standardize import LABELS, vocabulary

from ..models import ReviewItem

RULES = Path(__file__).resolve().parent.parent / "rules" / "matching.json"
MANAGED_KINDS = [ReviewItem.Kind.PAIR, ReviewItem.Kind.INCOMPLETE]
C = ReviewItem.Category
STRENGTH = {C.STRONG: "strong", C.NO_NUMBER: "medium", C.SAME_SOURCE: "medium",
            C.NUMBER_CONFLICT: "conflict", C.POSITION_CONFLICT: "conflict",
            C.SPEC_CONFLICT: "conflict", C.INSUFFICIENT: "weak", C.INCOMPLETE: "info"}


@cache
def rules() -> dict:
    return json.loads(RULES.read_text(encoding="utf-8"))


@dataclass
class Candidate:
    kind: str
    category: str
    a: SourceRecord
    b: SourceRecord | None = None
    triggers: list = field(default_factory=list)
    agreements: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    evidence_hash: str = ""

    @property
    def key(self):
        return (self.kind, identity(self.a), identity(self.b) if self.b else "")


def identity(record: SourceRecord) -> str:
    return f"{record.supplier_id}:{record.record_key}"


def find_candidates(records) -> list[Candidate]:
    """Recall (§8.1): a shared OE/cross number; the same part type on the same make and
    model; and, for records with no fitment at all, the same type, side and size."""
    records = sorted(records, key=identity)
    numbers = {r.pk: _numbers(r) for r in records}
    pairs: dict[tuple, tuple] = {}

    def add(group, only=None):
        if len(group) > rules()["max_block_size"]:
            return  # a block this big is a data problem, not a pairing
        for a, b in combinations(sorted(group, key=identity), 2):
            if only is None or a in only or b in only:
                pairs[(a.pk, b.pk)] = (a, b)

    by_number, by_fitment, by_size = defaultdict(list), defaultdict(list), defaultdict(list)
    for record in records:
        for number in numbers[record.pk]:
            by_number[number].append(record)
        if record.part_type and _fitment(record):
            by_fitment[(_norm(record.part_type), _norm(_fitment(record)))].append(record)
        if record.part_type and _dims(record):
            by_size[(_norm(record.part_type), record.position, _dims(record))].append(record)
    for group in [*by_number.values(), *by_fitment.values()]:
        add(group)
    for group in by_size.values():
        add(group, only=[r for r in group if not _fitment(r)])

    found = [c for a, b in pairs.values() if (c := judge(a, b, numbers))]
    found += [c for r in records if (c := _incomplete(r))]
    return found


def judge(a: SourceRecord, b: SourceRecord, numbers=None) -> Candidate | None:
    """Figure R3: type, then side, then missing fields, then fitment and size, then numbers."""
    numbers = numbers or {a.pk: _numbers(a), b.pk: _numbers(b)}
    shared = sorted(numbers[a.pk] & numbers[b.pk])
    c = Candidate(ReviewItem.Kind.PAIR, "", a, b)
    if shared:
        c.triggers.append(f"共享编号：{'、'.join(_originals(a, shared))}")
    elif _fitment(a) and _fitment(b):
        c.triggers.append(f"同品类、同车型：{a.part_type} · {_fitment(a)}")
    else:
        c.triggers.append(f"同品类、同位置、同尺寸，一方没有适配：{a.part_type}")

    part_type = _compare(c, "part_type", a.part_type, b.part_type)
    sided = any(vocabulary()["part_types"].get(r.part_type, {}).get("sided") for r in (a, b))
    position = _compare(c, "position", a.position, b.position, required=sided)
    fitment = _compare(c, "fitment", _fitment(a), _fitment(b))
    years = _compare_years(c, a, b)
    dims = _compare(c, "dims", _dims(a), _dims(b), equal=_dims_equal,
                    shown=(_dims(a, as_given=True), _dims(b, as_given=True)))
    if numbers[a.pk] and not numbers[b.pk] or numbers[b.pk] and not numbers[a.pk]:
        c.missing.append({"field": "oe_numbers", "label": LABELS["oe_numbers"],
                          "side": "b" if numbers[a.pk] else "a"})

    if part_type == "differ":
        category = C.NUMBER_CONFLICT if shared else None
    elif position == "differ":
        category = C.POSITION_CONFLICT if shared else None
    elif numbers[a.pk] and numbers[b.pk] and not shared:
        category = None  # both carry OE numbers and none is shared: different parts
    elif "missing" in (part_type, position, fitment, dims) or years == "missing":
        category = C.INSUFFICIENT
    elif "differ" in (fitment, dims) or years == "differ":
        category = C.SPEC_CONFLICT if shared else None
    elif shared:
        category = C.STRONG
    elif a.supplier_id == b.supplier_id:
        category = C.SAME_SOURCE
    else:
        category = C.NO_NUMBER
    if category is None:
        return None
    c.category = category
    c.evidence_hash = _hash(category, a, b)
    return c


def rematch() -> dict:
    """Bring undecided items in line with the current records and rules. Decided items
    stay decided while their evidence is unchanged; changed evidence reopens them.
    Item ids are kept for pairs whose evidence did not change."""
    records = (SourceRecord.objects.current().select_related("supplier")
               .prefetch_related("numbers"))
    candidates = find_candidates(records)
    counts = defaultdict(int)
    managed = ReviewItem.objects.filter(kind__in=MANAGED_KINDS)  # key changes are review's
    with transaction.atomic():
        open_items = {_key(i): i for i in managed.filter(status="open")}
        decided = {}
        for item in (managed.exclude(status__in=["open", "superseded"])
                     .order_by("decided_at", "id")):
            decided[_key(item)] = item
        seen = set()
        for candidate in candidates:
            seen.add(candidate.key)
            previous = decided.get(candidate.key)
            if previous and previous.evidence_hash == candidate.evidence_hash:
                counts["decided"] += 1
                continue
            values = _values(candidate)
            if previous:
                values["triggers"] = [f"证据已变化（上次决定：{previous.get_status_display()}）",
                                      *values["triggers"]]
                previous.status = ReviewItem.Status.SUPERSEDED
                previous.save(update_fields=["status", "updated_at"])
            existing = open_items.get(candidate.key)
            if existing is None:
                ReviewItem.objects.create(**values)
            elif (existing.evidence_hash, existing.rules_version, existing.record_a_id,
                  existing.record_b_id) != (values["evidence_hash"], values["rules_version"],
                                            candidate.a.pk, getattr(candidate.b, "pk", None)):
                ReviewItem.objects.filter(pk=existing.pk).update(**values)
            counts[candidate.category] += 1
        stale = [i.pk for k, i in open_items.items() if k not in seen]
        ReviewItem.objects.filter(pk__in=stale).delete()
        counts["removed"] = len(stale)
    return dict(counts)


# --- evidence ----------------------------------------------------------------------


def _compare(c, name, a_value, b_value, *, required=True, equal=None, shown=None):
    """Record agreement, conflict or missing value; returns same|differ|missing|skip.
    `shown` gives the values to display when they are compared in another form."""
    label = LABELS.get(name, name)
    if not a_value and not b_value:
        if required:
            c.missing.append({"field": name, "label": label, "side": "both"})
            return "missing"
        return "skip"
    if not a_value or not b_value:
        if required:
            c.missing.append({"field": name, "label": label, "side": "a" if not a_value else "b"})
            return "missing"
        return "skip"
    a_shown, b_shown = shown or (a_value, b_value)
    if (equal or _same)(a_value, b_value):
        c.agreements.append({"field": name, "label": label, "value": _show(name, a_shown)})
        return "same"
    c.conflicts.append({"field": name, "label": label,
                        "a": _side(c.a, name, a_shown), "b": _side(c.b, name, b_shown)})
    return "differ"


def _compare_years(c, a, b):
    years_a, years_b = (a.year_from, a.year_to), (b.year_from, b.year_to)
    if a.year_from is None and b.year_from is None:
        return "skip"  # neither states years; many catalogs never do
    if a.year_from is None or b.year_from is None:
        c.missing.append({"field": "years", "label": LABELS["years"],
                          "side": "a" if a.year_from is None else "b"})
        return "missing"
    if years_a == years_b:
        c.agreements.append({"field": "years", "label": LABELS["years"],
                             "value": _show("years", years_a)})
        return "same"
    a_to, b_to = a.year_to or 9999, b.year_to or 9999
    if a.year_from <= b_to and b.year_from <= a_to:
        c.agreements.append({"field": "years", "label": LABELS["years"],
                             "value": f"{_show('years', years_a)} 与 {_show('years', years_b)}",
                             "note": "年份区间部分重叠"})
        return "same"
    c.conflicts.append({"field": "years", "label": LABELS["years"],
                        "a": _side(a, "years", years_a), "b": _side(b, "years", years_b)})
    return "differ"


def _incomplete(record) -> Candidate | None:
    fields = [f for f in record.missing if f in rules()["incomplete_fields"]]
    if not fields:
        return None
    c = Candidate(ReviewItem.Kind.INCOMPLETE, C.INCOMPLETE, record)
    c.triggers.append(f"缺少：{'、'.join(LABELS.get(f, f) for f in fields)}")
    c.missing = [{"field": f, "label": LABELS.get(f, f), "side": "a"} for f in fields]
    c.evidence_hash = hashlib.sha256(json.dumps(
        [identity(record), sorted(fields)], ensure_ascii=False).encode()).hexdigest()
    return c


def _values(c: Candidate) -> dict:
    return {
        "kind": c.kind, "category": c.category, "strength": STRENGTH[c.category],
        "record_a": c.a, "record_b": c.b, "identity_a": identity(c.a),
        "identity_b": identity(c.b) if c.b else "", "triggers": c.triggers,
        "agreements": c.agreements, "conflicts": c.conflicts, "missing": c.missing,
        "suggested_action": rules()["actions"][c.category], "evidence_hash": c.evidence_hash,
        "rules_version": rules()["version"],
    }


def _hash(category, *records) -> str:
    """Key fields only, order-independent: a price change does not reopen a decision."""
    rows = sorted([identity(r), r.part_type, r.position, _norm(r.make), _norm(r.model),
                   r.year_from, r.year_to, [str(d) for d in _dims(r) or ()],
                   sorted(_numbers(r))] for r in records)
    return hashlib.sha256(json.dumps([str(category), rows], ensure_ascii=False)
                          .encode()).hexdigest()


def _key(item: ReviewItem):
    return (item.kind, item.identity_a, item.identity_b)


def _numbers(record) -> set[str]:
    kinds, shortest = rules()["recall_number_kinds"], rules()["min_number_length"]
    return {n.number_norm for n in record.numbers.all()
            if n.kind in kinds and len(n.number_norm) >= shortest}


def _originals(record, norms) -> list[str]:
    by_norm = {n.number_norm: n.number for n in record.numbers.all()}
    return [by_norm.get(n, n) for n in norms]


def _fitment(record) -> str:
    return f"{record.make} {record.model}".strip() if record.make and record.model else ""


def _dims(record, *, as_given=False):
    """Sorted for comparison (suppliers list the sides in different orders)."""
    values = (record.dim_l_cm, record.dim_w_cm, record.dim_h_cm)
    if any(v is None for v in values):
        return None
    return values if as_given else tuple(sorted(values))


def _dims_equal(a, b) -> bool:
    tolerance = Decimal(str(rules()["dims_tolerance_cm"]))
    return all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True))


def _same(a, b) -> bool:
    return _norm(a) == _norm(b)


def _norm(text) -> str:
    return "".join(str(text).casefold().split()).replace("-", "")


def _show(name, value) -> str:
    if name == "dims":
        return "×".join(f"{v.normalize():f}" for v in value) + " cm"
    if name == "years":
        return f"{value[0]}–{value[1] or '至今'}"
    return str(value)


def _side(record, name, value) -> dict:
    source_field = {"years": "fitment"}.get(name, name)
    return {"value": _show(name, value), "record": record.pk,
            "sources": record.fields.get(source_field, {}).get("sources", [])}


# --- record page hints ---------------------------------------------------------------

def hints(record: SourceRecord) -> list[str]:
    """Why lookalikes of this record were not paired (§8.2): the same fitment and size
    but another part type, the same type but the other side, or both sides with OE
    numbers none of which match. Read-only; nothing is proposed."""
    if not _fitment(record):
        return []
    mine = _numbers(record)
    others = (SourceRecord.objects.current().exclude(pk=record.pk)
              .filter(make__iexact=record.make).select_related("supplier")
              .prefetch_related("numbers"))
    notes = []
    for other in sorted(others, key=identity):
        if _norm(_fitment(other)) != _norm(_fitment(record)) or mine & _numbers(other):
            continue
        who = f"{other.supplier.name} {other.record_key}"
        same_type = _same(other.part_type, record.part_type)
        if not same_type and _dims(record) and _dims(other) and _dims_equal(_dims(record),
                                                                              _dims(other)):
            notes.append(f"同适配下 {who}（{other.part_type}）尺寸相同但品类不同，"
                         "已按品类区分，不配对")
        elif same_type and record.position and other.position and (
                record.position != other.position):
            notes.append(f"{who} 同品类同适配，但位置是 {other.position}，已按左右区分，不配对")
        elif same_type and mine and _numbers(other):
            notes.append(f"{who} 同品类同适配，但两边的 OE 号没有一个相同，视为不同产品")
    return notes
