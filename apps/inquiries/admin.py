from django.contrib import admin

from .models import Inquiry


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "input_type", "raw_input", "matched_part", "status", "created_by"]
    list_filter = ["input_type", "status"]
    list_select_related = ["matched_part", "created_by"]
    search_fields = ["raw_input", "customer", "matched_part__sku"]
    raw_id_fields = ["matched_part", "ai_task"]
    readonly_fields = ["finding", "created_by"]
