"""The only code that changes products and memberships (docs/archive-design.html §9).

Matching proposes; everything here records who did what in DecisionLog. M25 adds only
enroll(): each new record starts as its own unreviewed product. Human decisions are M26.
"""

from ..models import DecisionLog, Membership, Product


def enroll(records, *, source_file=None, user=None) -> int:
    """Give every record whose identity has no product yet a product of its own."""
    known = set(Membership.objects.filter(
        supplier_id__in={r.supplier_id for r in records},
        record_key__in={r.record_key for r in records},
    ).values_list("supplier_id", "record_key"))
    new = [r for r in records if (r.supplier_id, r.record_key) not in known]
    products = Product.objects.bulk_create([Product() for _ in new])
    Membership.objects.bulk_create([
        Membership(product=p, supplier_id=r.supplier_id, record_key=r.record_key,
                   current_record=r, joined_by=user)
        for p, r in zip(products, new, strict=True)
    ])
    if new:
        DecisionLog.objects.create(action="enroll", actor=user, payload={
            "说明": "新记录各自成为待核产品", "source_file": getattr(source_file, "pk", None),
            "records": [r.pk for r in new], "products": [p.pk for p in products],
        })
    return len(new)
