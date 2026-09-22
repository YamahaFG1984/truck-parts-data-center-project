"""One box over the archive (docs/archive-design.html §11): any number, a keyword, a
brand or a supplier name. Current record versions are searched; results are grouped
by product and say which record's which field matched."""

from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Q

from apps.catalog.services.normalize import normalize_number
from apps.sources.models import RecordNumber, SourceRecord

from ..models import Membership, Product

LIMIT = 50
CONTAINS_FROM = 5  # a partial number shorter than this matches too much ("01")
TEXT_FIELDS = [("name", "原始名称"), ("part_type", "品类"), ("model", "适配车型"),
               ("make", "适配品牌"), ("fields__brand__value", "品牌"),
               ("supplier__name", "供应商")]


@dataclass
class Hit:
    record: SourceRecord
    label: str
    value: str


@dataclass
class Result:
    product: Product
    hits: list = field(default_factory=list)
    by_number: bool = False


def search(query: str, supplier=None) -> list[Result]:
    query = (query or "").strip()
    if not query:
        return []
    current = SourceRecord.objects.current()
    if supplier is not None:
        current = current.filter(supplier=supplier)
    hits: dict[int, list[Hit]] = defaultdict(list)
    numbered = set()
    for number in _numbers(query, current):
        hits[number.record_id].append(Hit(number.record, number.get_kind_display(),
                                          number.number))
        numbered.add(number.record_id)
    text = Q()
    for name, _ in TEXT_FIELDS:
        text |= Q(**{f"{name}__icontains": query})
    for record in current.filter(text).select_related("supplier")[:LIMIT * 4]:
        for name, label in TEXT_FIELDS:
            value = _get(record, name)
            if value and query.casefold() in value.casefold():
                hits[record.pk].append(Hit(record, label, value))
    return _by_product(hits, numbered)


def _numbers(query, current):
    """Exact normalized number first; a partial number only if nothing matched exactly."""
    norm = normalize_number(query)
    if not norm:
        return []
    numbers = RecordNumber.objects.filter(record__in=current).select_related(
        "record__supplier")
    exact = list(numbers.filter(number_norm=norm)[:LIMIT * 4])
    if exact or len(norm) < CONTAINS_FROM:
        return exact
    return list(numbers.filter(number_norm__contains=norm)[:LIMIT * 4])


def _by_product(hits, numbered) -> list[Result]:
    records = {h.record.pk: h.record for found in hits.values() for h in found}
    identities = {(r.supplier_id, r.record_key): pk for pk, r in records.items()}
    results: dict[int, Result] = {}
    memberships = Membership.objects.select_related("product").filter(
        supplier_id__in={s for s, _ in identities}, record_key__in={k for _, k in identities})
    for m in memberships:
        pk = identities.get((m.supplier_id, m.record_key))
        if pk is None:
            continue
        result = results.setdefault(m.product_id, Result(m.product))
        result.hits += hits[pk]
        result.by_number = result.by_number or pk in numbered
    ordered = sorted(results.values(), key=lambda r: (not r.by_number, -len(r.hits),
                                                      r.product.pk))
    return ordered[:LIMIT]


def _get(record, name) -> str:
    if name == "supplier__name":
        return record.supplier.name
    if name == "fields__brand__value":
        return str(record.fields.get("brand", {}).get("value") or "")
    return str(getattr(record, name) or "")
