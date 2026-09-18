from django.contrib import admin

from .models import ImportBatch, ImportRow


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "original_name", "supplier", "status", "header_row", "created_by",
                    "created_at"]
    list_filter = ["status", "supplier"]
    list_select_related = ["supplier", "created_by"]
    search_fields = ["original_name"]
    readonly_fields = ["file", "original_name", "header_row", "stats", "created_by",
                       "created_at", "updated_at"]


@admin.register(ImportRow)
class ImportRowAdmin(admin.ModelAdmin):
    list_display = ["batch", "row_no", "result", "part", "message"]
    list_filter = ["result", "batch"]
    list_select_related = ["batch", "part"]
    search_fields = ["message", "part__sku"]
    readonly_fields = ["batch", "row_no", "raw", "result", "message", "part"]
