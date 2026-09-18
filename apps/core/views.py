from django.views.generic import DetailView, TemplateView

from apps.catalog.services.quality import MISSING_LABELS, duplicates, summary

from .jobs import worker_missing
from .models import Job

MAX_DUPLICATE_GROUPS = 50


class HomeView(TemplateView):
    """Placeholder home page; the real dashboard arrives in M20."""

    template_name = "core/home.html"


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
