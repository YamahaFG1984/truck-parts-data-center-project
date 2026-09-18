"""Django Admin for the catalog: the fallback editor for every product field."""

from django.contrib import admin
from django.db.models import Count, Prefetch
from django.utils import timezone
from django.utils.html import format_html

from .models import Brand, Category, Fitment, Part, PartImage, PartNumber
from .services.normalize import normalize_number
from .services.quality import recompute


def _score_badge(score: int) -> str:
    color = "#b91c1c" if score < 40 else "#b45309" if score < 70 else "#047857"
    return format_html(
        '<span style="color:#fff;background:{};border-radius:9px;padding:1px 8px">{}</span>',
        color,
        score,
    )


def _thumb(image: PartImage | None, height: int = 40) -> str:
    if not image or not image.image:
        return "—"
    return format_html(
        '<img src="{}" style="height:{}px;border-radius:4px">', image.image.url, height
    )


class NormalizedNumberSearchMixin:
    """Admin search also matches part numbers by their normalized form.

    "2044-3906" and "20 443 906" both find 20443906. Set number_lookup to the
    path of the number_norm field from this admin's model.
    """

    number_lookup = "number_norm"

    def get_search_results(self, request, queryset, search_term):
        results, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        norm = normalize_number(search_term)
        if norm:
            results |= queryset.filter(**{f"{self.number_lookup}__contains": norm})
            may_have_duplicates = True
        return results, may_have_duplicates


class SourcedAdminMixin:
    """Stamp who confirmed a record and when, whenever "verified" gets ticked."""

    def _stamp_verified(self, request, obj):
        if obj.verified and not obj.verified_by_id:
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
        elif not obj.verified:
            obj.verified_by = None
            obj.verified_at = None

    def save_model(self, request, obj, form, change):
        self._stamp_verified(request, obj)
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if hasattr(obj, "verified"):
                self._stamp_verified(request, obj)
            obj.save()
        formset.save_m2m()


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "name_en", "code", "parent", "part_count"]
    list_select_related = ["parent"]
    list_filter = ["parent"]
    search_fields = ["name", "name_en", "code"]
    autocomplete_fields = ["parent"]
    # Explicit: the Count annotation below makes the model's default ordering
    # not count, and unordered pagination can shuffle autocomplete results.
    ordering = ["parent__name", "name"]

    def get_queryset(self, request):
        # One aggregate query instead of a count per row.
        return super().get_queryset(request).annotate(_part_count=Count("parts"))

    @admin.display(description="产品数", ordering="_part_count")
    def part_count(self, obj):
        return obj._part_count


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["name", "kind"]
    list_filter = ["kind"]
    search_fields = ["name"]


class PartNumberInline(admin.TabularInline):
    model = PartNumber
    extra = 0
    fields = ["number", "number_norm", "kind", "brand", "source", "confidence", "verified"]
    readonly_fields = ["number_norm"]
    autocomplete_fields = ["brand"]


class FitmentInline(admin.TabularInline):
    model = Fitment
    extra = 0
    fields = ["make", "model", "engine", "year_from", "year_to", "notes", "source", "verified"]


class PartImageInline(admin.TabularInline):
    model = PartImage
    extra = 0
    fields = ["preview", "image", "is_primary", "caption", "source"]
    readonly_fields = ["preview"]

    @admin.display(description="预览")
    def preview(self, obj):
        return _thumb(obj, height=60)


@admin.register(Part)
class PartAdmin(NormalizedNumberSearchMixin, SourcedAdminMixin, admin.ModelAdmin):
    number_lookup = "numbers__number_norm"

    list_display = ["sku", "thumbnail", "name_en", "category", "status", "score", "source"]
    list_display_links = ["sku", "name_en"]
    list_filter = ["status", "category", "source", "verified"]
    list_select_related = ["category"]
    search_fields = ["sku", "name_en", "name_zh", "numbers__number_norm"]
    autocomplete_fields = ["category"]
    readonly_fields = [
        "completeness_score", "verified_by", "verified_at", "created_at", "updated_at",
    ]
    list_per_page = 50
    inlines = [PartNumberInline, FitmentInline, PartImageInline]
    fieldsets = [
        (None, {"fields": ["sku", "name_en", "name_zh", "category", "status"]}),
        (
            "规格与内容",
            {"fields": ["attributes", "packaging", "description_en", "keywords", "notes"]},
        ),
        (
            "来源与质量",
            {
                "fields": [
                    "completeness_score", "source", "confidence", "verified",
                    "verified_by", "verified_at", "created_at", "updated_at",
                ]
            },
        ),
    ]

    def get_queryset(self, request):
        primary = PartImage.objects.filter(is_primary=True)
        return (
            super()
            .get_queryset(request)
            .prefetch_related(Prefetch("images", queryset=primary, to_attr="primary_images"))
        )

    def save_related(self, request, form, formsets, change):
        """Inlines (numbers, fitments, images) are saved here, so score afterwards."""
        super().save_related(request, form, formsets, change)
        recompute(Part.objects.filter(pk=form.instance.pk))

    @admin.display(description="主图")
    def thumbnail(self, obj):
        images = getattr(obj, "primary_images", None)
        return _thumb(images[0] if images else None)

    @admin.display(description="完整度", ordering="completeness_score")
    def score(self, obj):
        return _score_badge(obj.completeness_score)


@admin.register(PartNumber)
class PartNumberAdmin(NormalizedNumberSearchMixin, SourcedAdminMixin, admin.ModelAdmin):
    list_display = ["number", "number_norm", "kind", "brand", "part", "source", "verified"]
    list_filter = ["kind", "source", "verified", "brand"]
    list_select_related = ["part", "brand"]
    search_fields = ["number", "number_norm", "part__sku"]
    autocomplete_fields = ["part", "brand"]
    readonly_fields = ["number_norm", "verified_by", "verified_at"]
