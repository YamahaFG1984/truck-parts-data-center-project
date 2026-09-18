from django.contrib import admin

from .models import AITask


@admin.register(AITask)
class AITaskAdmin(admin.ModelAdmin):
    list_display = ["created_at", "prompt_name", "model", "status", "attempts", "prompt_tokens",
                    "completion_tokens", "latency_ms"]
    list_filter = ["status", "prompt_name", "provider", "model"]
    search_fields = ["input_digest", "input_preview", "error"]
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):  # audit rows are never edited
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False
