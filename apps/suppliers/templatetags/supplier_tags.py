from django import template

from ..services.quoting import best_offer as _best_offer
from ..services.quoting import suggested_price as _suggested_price

register = template.Library()


@register.filter
def best_offer(part):
    """Cheapest offer from prefetched offers (no extra query)."""
    return _best_offer(part)


@register.filter
def suggested_price(cost):
    return _suggested_price(cost)
