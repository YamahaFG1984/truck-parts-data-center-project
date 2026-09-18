from django.views.generic import TemplateView

from apps.catalog.services.quality import MISSING_LABELS, duplicates, summary

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
