"""The only code that changes products and memberships (docs/archive-design.html §9).

Matching proposes; people decide here. Every function records who did what and why in
DecisionLog, and every merge can be undone with detach(). A guard test fails if any
other module writes memberships or product grouping.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.sources.models import SourceRecord

from ..models import DecisionLog, FieldChoice, Membership, Product, ReviewItem

S = ReviewItem.Status


class ReviewError(ValueError):
    """The decision is refused; the message is shown to the person."""


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
        _log("enroll", user, 说明="新记录各自成为待核产品",
             source_file=getattr(source_file, "pk", None),
             records=[r.pk for r in new], products=[p.pk for p in products])
    return len(new)


def membership_of(record: SourceRecord) -> Membership:
    return Membership.objects.select_related("product").get(
        supplier_id=record.supplier_id, record_key=record.record_key)


# --- decisions on review items --------------------------------------------------------


@transaction.atomic
def confirm_same(item: ReviewItem, user, note: str = "") -> Product:
    """Put both records in one product. Refused if any pair across the two products
    was judged different: that decision has to be undone first, on purpose."""
    _check(item, ReviewItem.Kind.PAIR)
    first, second = membership_of(item.record_a).product, membership_of(item.record_b).product
    survivor = first
    if first.pk != second.pk:
        _refuse_if_judged_different(first, second)
        survivor, absorbed = sorted([first, second], key=lambda p: p.pk)
        moved = list(absorbed.memberships.values_list("record_key", flat=True))
        absorbed.memberships.update(product=survivor)
        absorbed.choices.all().delete()  # they were about the absorbed product's members
        absorbed.status, absorbed.merged_into = Product.Status.MERGED, survivor
        absorbed.save(update_fields=["status", "merged_into", "updated_at"])
        _log("merge", user, item, into=survivor.code, absorbed=absorbed.code, records=moved,
             note=note)
        if absorbed.needs_info:  # an open "to be completed" flag must not get lost
            survivor.needs_info = True
            survivor.missing_fields = sorted({*survivor.missing_fields,
                                              *absorbed.missing_fields})
    survivor.status = Product.Status.GROUPED
    survivor.save(update_fields=["status", "needs_info", "missing_fields", "updated_at"])
    _decide(item, S.SAME, user, note)
    _close_implied(survivor, user, item)
    return survivor


@transaction.atomic
def mark_different(item: ReviewItem, user, note: str = "") -> None:
    _check(item, ReviewItem.Kind.PAIR)
    if membership_of(item.record_a).product_id == membership_of(item.record_b).product_id:
        raise ReviewError("这两条记录已在同一产品中；如认为不是同一件，请先把其中一条移出。")
    _decide(item, S.DIFFERENT, user, note)
    _log("mark_different", user, item, note=note)


@transaction.atomic
def confirm_independent(item: ReviewItem, user, note: str = "") -> Product:
    """For a record's own item: it stands alone as it is."""
    _check(item, ReviewItem.Kind.INCOMPLETE)
    product = membership_of(item.record_a).product
    if product.memberships.count() > 1:
        raise ReviewError(f"{product.code} 已有多条成员，不能确认为独立产品。")
    product.status = Product.Status.INDEPENDENT
    product.save(update_fields=["status", "updated_at"])
    _decide(item, S.INDEPENDENT, user, note)
    _log("confirm_independent", user, item, product=product.code, note=note)
    return product


@transaction.atomic
def mark_needs_info(item: ReviewItem, user, note: str = "") -> Product:
    _check(item, ReviewItem.Kind.INCOMPLETE)
    product = membership_of(item.record_a).product
    fields = sorted({*product.missing_fields, *(m["field"] for m in item.missing)})
    product.needs_info, product.missing_fields = True, fields
    product.save(update_fields=["needs_info", "missing_fields", "updated_at"])
    _decide(item, S.NEEDS_INFO, user, note)
    _log("mark_needs_info", user, item, product=product.code, fields=fields, note=note)
    return product


def bulk_confirm(items, user, note: str = "") -> tuple[list, list]:
    """Confirm strong items one by one, each logged; anything else is refused."""
    done, refused = [], []
    for item in items:
        if item.category != ReviewItem.Category.STRONG:
            refused.append((item, "只有强证据条目可以批量确认"))
            continue
        try:
            confirm_same(item, user, note or "批量确认（强证据）")
            done.append(item)
        except ReviewError as exc:
            refused.append((item, str(exc)))
    return done, refused


# --- decisions on products ------------------------------------------------------------


@transaction.atomic
def detach(membership: Membership, user, note: str = "") -> Product:
    """Take a record out of its product into a new unreviewed one: the undo of a merge.
    Same-product decisions involving the record are superseded and matching reruns,
    so those pairs come back as open questions."""
    from . import matching

    old = membership.product
    if old.memberships.count() < 2:
        raise ReviewError(f"{old.code} 只有这一条成员，无需移出。")
    new = Product.objects.create()
    membership.product = new
    membership.save(update_fields=["product", "updated_at"])
    if old.memberships.count() == 1:
        old.status = Product.Status.UNREVIEWED
        old.save(update_fields=["status", "updated_at"])
    identity = f"{membership.supplier_id}:{membership.record_key}"
    undone = list(ReviewItem.objects.filter(Q(identity_a=identity) | Q(identity_b=identity),
                                            status=S.SAME).values_list("pk", flat=True))
    ReviewItem.objects.filter(pk__in=undone).update(status=S.SUPERSEDED)
    _log("detach", user, record=membership.record_key, from_product=old.code, to_product=new.code,
         superseded_items=undone, note=note)
    matching.rematch()
    return new


@transaction.atomic
def choose_value(product: Product, field: str, record: SourceRecord, user, reason: str):
    """Pick which member's value the product shows for a field members disagree on."""
    if not product.memberships.filter(current_record=record).exists():
        raise ReviewError("只能从该产品当前成员的取值里选择。")
    if not reason.strip():
        raise ReviewError("请写明选择依据。")
    value = record.fields.get(field, {}).get("value")
    choice, _ = FieldChoice.objects.update_or_create(
        product=product, field=field,
        defaults={"record": record, "value": value, "chosen_by": user, "reason": reason})
    _log("choose_value", user, product=product.code, field=field, record=record.pk,
         value=value, reason=reason)
    return choice


# --- helpers ---------------------------------------------------------------------------


def _check(item: ReviewItem, kind: str) -> None:
    if item.status != S.OPEN:
        raise ReviewError(f"条目 #{item.pk} 已处理（{item.get_status_display()}）。")
    if item.kind != kind:
        raise ReviewError("这个动作不适用于该类条目。")


def _decide(item: ReviewItem, status: str, user, note: str) -> None:
    item.status, item.decided_by, item.decided_at, item.note = status, user, timezone.now(), note
    item.save(update_fields=["status", "decided_by", "decided_at", "note", "updated_at"])


def _identities(product: Product) -> set[str]:
    return {f"{s}:{k}" for s, k in product.memberships.values_list("supplier_id", "record_key")}


def _refuse_if_judged_different(first: Product, second: Product) -> None:
    left, right = _identities(first), _identities(second)
    for item in ReviewItem.objects.filter(status=S.DIFFERENT, kind=ReviewItem.Kind.PAIR):
        if {item.identity_a, item.identity_b} & left and {item.identity_a, item.identity_b} & right:
            raise ReviewError(
                f"{item.identity_a.split(':', 1)[1]} 与 {item.identity_b.split(':', 1)[1]} "
                f"已被判为不同产品（条目 #{item.pk}），不能合并；如需合并请先重新审视该决定。")


def _close_implied(product: Product, user, source: ReviewItem) -> None:
    """Open pair items whose two records now sit in the same product are answered."""
    members = _identities(product)
    implied = [i for i in ReviewItem.objects.filter(status=S.OPEN, kind=ReviewItem.Kind.PAIR)
               if i.identity_a in members and i.identity_b in members]
    for item in implied:
        _decide(item, S.SAME, user, f"由条目 #{source.pk} 的决定推出：两条记录已在 {product.code}")
    if implied:
        _log("implied_same", user, source, product=product.code, items=[i.pk for i in implied])


def _log(action: str, user, item: ReviewItem | None = None, **payload) -> DecisionLog:
    return DecisionLog.objects.create(action=action, actor=user, review_item=item,
                                      payload=payload)
