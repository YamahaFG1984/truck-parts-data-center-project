from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views import View
from django.views.generic import ListView

from apps.catalog.models import Part

from .llm.base import LLMError
from .models import AISuggestion
from .services.enrich import enrich_part

CARD = "ai/partials/suggestion.html"


def _card(request, suggestion=None, error="", part=None):
    return TemplateResponse(request, CARD, {"suggestion": suggestion, "error": error, "part": part})


class EnrichView(View):
    """POST: generate (or reuse) a pending suggestion for one part."""

    def post(self, request, sku):
        part = get_object_or_404(
            Part.objects.select_related("category").prefetch_related("numbers", "fitments"), sku=sku
        )
        try:
            suggestion = enrich_part(part)
        except (LLMError, ImproperlyConfigured) as exc:
            if request.htmx:
                return _card(request, error=f"AI 补全失败：{exc}", part=part)
            messages.error(request, f"AI 补全失败：{exc}")
            return redirect("catalog:part_detail", sku=sku)
        if request.htmx:
            return _card(request, suggestion)
        return redirect("ai:review_queue")


class ReviewQueueView(ListView):
    """Pending suggestions first; ?status=accepted|rejected shows the history."""

    template_name = "ai/review_queue.html"
    context_object_name = "suggestions"
    paginate_by = 20

    def get_queryset(self):
        self.status = self.request.GET.get("status", AISuggestion.Status.PENDING)
        if self.status not in AISuggestion.Status.values:
            self.status = AISuggestion.Status.PENDING
        return (
            AISuggestion.objects.filter(status=self.status)
            .select_related("part__category", "ai_task", "reviewed_by")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = {s: 0 for s in AISuggestion.Status.values}
        for status in AISuggestion.objects.values_list("status", flat=True):
            counts[status] += 1
        context.update(
            status=self.status,
            tabs=[(value, label, counts[value]) for value, label in AISuggestion.Status.choices],
        )
        return context


class _ReviewAction(View):
    def post(self, request, pk):
        suggestion = get_object_or_404(AISuggestion.objects.select_related("part__category"), pk=pk)
        try:
            message = self.act(suggestion, request)
        except ValueError as exc:
            message, level = str(exc), messages.ERROR
        else:
            level = messages.SUCCESS
        if request.htmx:
            return TemplateResponse(request, CARD, {"suggestion": suggestion, "flash": message,
                                                    "flash_error": level == messages.ERROR})
        messages.add_message(request, level, message)
        return redirect(request.POST.get("next") or "ai:review_queue")


class AcceptView(_ReviewAction):
    def act(self, suggestion, request):
        applied = suggestion.accept(request.user, request.POST.getlist("fields"))
        if not applied:
            return f"{suggestion.part.sku}：没有字段被采纳。"
        return f"{suggestion.part.sku} 已采纳 {len(applied)} 个字段，完整度已重算。"


class RejectView(_ReviewAction):
    def act(self, suggestion, request):
        suggestion.reject(request.user, request.POST.get("reason", ""))
        return f"{suggestion.part.sku} 的建议已拒绝，原因已记录。"
