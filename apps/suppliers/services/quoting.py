"""Price rules for quotes (docs/architecture.html §7.6). Decimal only, never float."""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

CENT = Decimal("0.01")


def best_offer(part):
    """Cheapest offer; on equal price the shorter lead time wins. None if no offers.

    Uses prefetched offers when present, so callers rendering many parts stay at
    one query (SupplierOffer.Meta.ordering applies the same rule in SQL).
    """
    offers = list(part.offers.all())
    if not offers:
        return None
    return min(offers, key=lambda o: (o.unit_cost_usd, o.lead_days is None, o.lead_days or 0, o.pk))


def suggested_price(cost: Decimal | None, margin: Decimal | None = None) -> Decimal | None:
    """cost x (1 + margin), rounded half-up to cents. Margin defaults to DEFAULT_MARGIN."""
    if cost is None:
        return None
    margin = settings.DEFAULT_MARGIN if margin is None else Decimal(margin)
    return (Decimal(cost) * (1 + margin)).quantize(CENT, rounding=ROUND_HALF_UP)
