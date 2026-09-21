"""Read-only admin: the source layer is changed only by the import services."""

from django.contrib import admin

from .models import MappingTemplate, RecordNumber, SourceFile, SourceRecord


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SourceFile)
class SourceFileAdmin(ReadOnlyAdmin):
    list_display = ["id", "original_name", "supplier", "file_format", "status", "size_bytes",
                    "uploaded_by", "created_at"]
    list_filter = ["status", "file_format", "supplier"]
    list_select_related = ["supplier", "uploaded_by"]
    search_fields = ["original_name", "sha256"]


class RecordNumberInline(admin.TabularInline):
    model = RecordNumber
    fields = ["kind", "number", "number_norm"]
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SourceRecord)
class SourceRecordAdmin(ReadOnlyAdmin):
    list_display = ["id", "supplier", "record_key", "version", "change_type", "locator",
                    "part_type", "position", "price", "currency", "source_file"]
    list_filter = ["supplier", "change_type", "part_type", "currency"]
    list_select_related = ["supplier", "source_file"]
    search_fields = ["record_key", "supplier_sku", "name", "numbers__number_norm"]
    inlines = [RecordNumberInline]


@admin.register(MappingTemplate)
class MappingTemplateAdmin(admin.ModelAdmin):
    """Templates may be deleted (to force a fresh mapping) but are edited only by
    confirming a mapping in the import flow."""

    list_display = ["supplier", "header_signature", "confirmed_by", "updated_at"]
    list_select_related = ["supplier", "confirmed_by"]
    readonly_fields = ["supplier", "header_signature", "headers", "columns", "confirmed_by"]

    def has_add_permission(self, request, obj=None):
        return False
