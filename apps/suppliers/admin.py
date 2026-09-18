from django.contrib import admin
from django.db.models import Count

from .models import Supplier, SupplierOffer


class SupplierOfferInline(admin.TabularInline):
    model = SupplierOffer
    extra = 0
    fields = ["part", "supplier_pn", "unit_cost_usd", "moq", "lead_days", "price_term", "quoted_at"]
    autocomplete_fields = ["part"]
    show_change_link = True


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "rating", "contact", "offer_count"]
    list_filter = ["country", "rating"]
    search_fields = ["name", "contact", "notes"]
    ordering = ["name"]
    inlines = [SupplierOfferInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_offer_count=Count("offers"))

    @admin.display(description="报价数", ordering="_offer_count")
    def offer_count(self, obj):
        return obj._offer_count


@admin.register(SupplierOffer)
class SupplierOfferAdmin(admin.ModelAdmin):
    list_display = [
        "part", "supplier", "supplier_pn", "unit_cost_usd", "moq", "lead_days",
        "price_term", "quoted_at",
    ]
    list_filter = ["supplier", "price_term", "quoted_at"]
    list_select_related = ["part", "supplier"]
    search_fields = ["part__sku", "supplier_pn", "supplier__name"]
    autocomplete_fields = ["part", "supplier"]
    date_hierarchy = "quoted_at"
