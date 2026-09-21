"""Read-only admin: products and memberships change only through the review service."""

from django.contrib import admin

from apps.sources.admin import ReadOnlyAdmin

from .models import DecisionLog, FieldChoice, Membership, Product, ReviewItem


class MembershipInline(admin.TabularInline):
    model = Membership
    fields = ["supplier", "record_key", "current_record", "status", "joined_by"]
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(ReadOnlyAdmin):
    list_display = ["id", "status", "needs_info", "created_at"]
    list_filter = ["status", "needs_info"]
    inlines = [MembershipInline]


@admin.register(ReviewItem)
class ReviewItemAdmin(ReadOnlyAdmin):
    list_display = ["id", "category", "strength", "status", "identity_a", "identity_b",
                    "rules_version"]
    list_filter = ["status", "category", "kind"]
    search_fields = ["identity_a", "identity_b"]


@admin.register(DecisionLog)
class DecisionLogAdmin(ReadOnlyAdmin):
    list_display = ["at", "action", "actor", "review_item"]
    list_filter = ["action"]


admin.site.register(FieldChoice, ReadOnlyAdmin)
