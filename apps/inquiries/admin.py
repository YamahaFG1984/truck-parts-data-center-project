from django.contrib import admin

from .models import Inquiry, QuoteLine


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "input_type", "raw_input", "matched_part", "status", "created_by"]
    list_filter = ["input_type", "status"]
    list_select_related = ["matched_part", "created_by"]
    search_fields = ["raw_input", "customer", "matched_part__sku"]
    raw_id_fields = ["matched_part", "ai_task"]
    readonly_fields = ["finding", "query_key", "created_by"]


@admin.register(QuoteLine)
class QuoteLineAdmin(admin.ModelAdmin):
    list_display = ["inquiry", "part", "qty", "unit_cost_usd", "margin", "unit_price_usd", "note"]
    list_select_related = ["inquiry", "part"]
    raw_id_fields = ["inquiry", "part", "offer"]
