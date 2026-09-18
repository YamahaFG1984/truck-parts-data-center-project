"""QuerySets for catalog models. Admin, services and views all go through these."""

from django.db import models
from django.db.models import (
    Exists,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    prefetch_related_objects,
)

from .services.normalize import normalize_number


def has_related(model_label: str, **filters) -> Exists:
    """Exists() over a model with a `part` FK. Resolved by name at call time, so
    catalog never imports other apps (suppliers depends on catalog, not back)."""
    from django.apps import apps

    app_label, _, model_name = model_label.rpartition(".")
    model = apps.get_model(app_label or "catalog", model_name)
    return Exists(model.objects.filter(part=OuterRef("pk"), **filters))


# Each entry answers "which parts lack X". Keys are shared with the quality
# dashboard (M10/M11).
MISSING_FILTERS = {
    "name": lambda: Q(name_en=""),
    "category": lambda: Q(category__isnull=True),
    "oe": lambda: ~has_related("PartNumber", kind="OE"),
    "cross": lambda: ~has_related("PartNumber", kind="CROSS"),
    "fitment": lambda: ~has_related("Fitment"),
    "image": lambda: ~has_related("PartImage", is_primary=True),
    "description": lambda: Q(description_en=""),
    "packaging": lambda: Q(packaging={}),
    "offer": lambda: ~has_related("suppliers.SupplierOffer"),
}


class PartQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status="published")

    def reviewed(self):
        """Reviewed by a person, including parts already published."""
        return self.filter(status__in=["reviewed", "published"])

    def missing(self, item: str):
        try:
            condition = MISSING_FILTERS[item]()
        except KeyError:
            raise ValueError(f"unknown missing item {item!r}; use one of {list(MISSING_FILTERS)}")
        return self.filter(condition)

    def with_min_cost(self):
        """Annotate min_cost: the cheapest offer's unit cost (None without offers)."""
        from django.apps import apps

        offers = apps.get_model("suppliers", "SupplierOffer").objects.filter(part=OuterRef("pk"))
        return self.annotate(
            min_cost=Subquery(offers.order_by("unit_cost_usd").values("unit_cost_usd")[:1])
        )

    def with_related(self):
        """Everything a part card shows, in a fixed number of queries."""
        return self.select_related("category__parent").prefetch_related(*card_prefetches())


def card_prefetches() -> list:
    """Related rows a part card or detail page needs: numbers+brand, fitments, images,
    offers."""
    from .models import PartImage, PartNumber

    return [
        Prefetch(
            "numbers",
            queryset=PartNumber.objects.select_related("brand").order_by("kind", "number"),
        ),
        "fitments",
        Prefetch("images", queryset=PartImage.objects.order_by("-is_primary", "id")),
        "offers",  # suppliers.SupplierOffer, cheapest first by its Meta.ordering
    ]


def prefetch_for_cards(parts: list) -> list:
    """Attach card data to parts already in memory (e.g. from the matcher): 4 queries."""
    prefetch_related_objects(parts, *card_prefetches())
    return parts


class PartNumberQuerySet(models.QuerySet):
    def of_kind(self, kind: str):
        return self.filter(kind=kind)

    def bulk_create(self, objs, *args, **kwargs):
        # bulk_create skips save(); keep number_norm correct for importers too.
        objs = list(objs)
        for obj in objs:
            obj.number = (obj.number or "").strip()
            obj.number_norm = normalize_number(obj.number)
        return super().bulk_create(objs, *args, **kwargs)
