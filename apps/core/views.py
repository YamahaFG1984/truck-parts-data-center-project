from django.conf import settings
from django.views.generic import DetailView, TemplateView

from apps.ai.models import AISuggestion
from apps.catalog.services.quality import MISSING_LABELS, duplicates, summary
from apps.inquiries.models import Inquiry

from .jobs import worker_missing
from .models import Job

MAX_DUPLICATE_GROUPS = 50
RECENT_INQUIRIES = 6
TOP_MISSING = 4


class HomeView(TemplateView):
    """Where the demo starts: one search box, the data health numbers, what is
    waiting for review, and the latest inquiries."""

    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stats = summary()
        by_count = sorted(stats["missing"].items(), key=lambda kv: -kv[1])
        context.update(
            stats=stats,
            # Empty on an empty database, so the page says "seed the demo data"
            # instead of showing four bars that are all zero.
            top_missing=[
                {"key": key, "label": MISSING_LABELS[key], "count": count,
                 "percent": round(100 * count / stats["total"])}
                for key, count in by_count[:TOP_MISSING]
            ] if stats["total"] else [],
            pending=AISuggestion.objects.filter(status=AISuggestion.Status.PENDING).count(),
            inquiries=Inquiry.objects.settled().select_related("matched_part")[:RECENT_INQUIRIES],
            mock=settings.LLM_PROVIDER == "mock",
        )
        return context


class QualityDashboardView(TemplateView):
    """Data health at a glance; every number links to the parts behind it."""

    template_name = "core/quality.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stats = summary()
        total = stats["total"] or 1
        context.update(
            stats=stats,
            buckets=[
                bucket | {"percent": round(100 * bucket["count"] / total)}
                for bucket in stats["distribution"]
            ],
            missing=[
                {"key": key, "label": MISSING_LABELS[key], "count": count,
                 "percent": round(100 * count / total)}
                for key, count in sorted(stats["missing"].items(), key=lambda kv: -kv[1])
            ],
            duplicate_groups=duplicates()[:MAX_DUPLICATE_GROUPS],
        )
        return context


class JobView(DetailView):
    """Progress of a background job; the HTMX fragment polls itself every 2 s until done."""

    model = Job
    context_object_name = "job"

    def get_template_names(self):
        return ["core/partials/job_progress.html" if self.request.htmx else "core/job.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["worker_missing"] = worker_missing(self.object)
        return context
