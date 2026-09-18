"""QuerySets for catalog models. Admin, services and views all go through these."""

from django.db import models
from django.db.models import Exists, OuterRef, Prefetch, Q

from .services.normalize import normalize_number


def _has(related_model_name: str, **filters) -> Exists:
    from django.apps import apps

    model = apps.get_model("catalog", related_model_name)
    return Exists(model.objects.filter(part=OuterRef("pk"), **filters))


# Each entry answers "which parts lack X". Keys are shared with the quality
# dashboard (M10/M11); SupplierOffer ("offer") joins in M09.
MISSING_FILTERS = {
    "name": lambda: Q(name_en=""),
    "category": lambda: Q(category__isnull=True),
    "oe": lambda: ~_has("PartNumber", kind="OE"),
    "cross": lambda: ~_has("PartNumber", kind="CROSS"),
    "fitment": lambda: ~_has("Fitment"),
    "image": lambda: ~_has("PartImage", is_primary=True),
    "description": lambda: Q(description_en=""),
    "packaging": lambda: Q(packaging={}),
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

    def with_related(self):
        """Everything a part card shows, in a fixed number of queries."""
        from .models import PartImage, PartNumber

        return self.select_related("category").prefetch_related(
            Prefetch(
                "numbers",
                queryset=PartNumber.objects.select_related("brand").order_by("kind", "number"),
            ),
            "fitments",
            Prefetch("images", queryset=PartImage.objects.order_by("-is_primary", "id")),
        )


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
