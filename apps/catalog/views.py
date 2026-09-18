from django.views.generic import DetailView, TemplateView

from .managers import prefetch_for_cards
from .models import Part
from .services.matcher import alternatives, search
from .services.normalize import detect_query_kind

MAX_QUERY_LENGTH = 200
_KIND_LABELS = {"number": "编号", "sku": "SKU", "text": "名称 / 车型"}


class SearchView(TemplateView):
    """One search box for OE / cross / SKU / names. HTMX requests get only the results."""

    template_name = "catalog/search.html"
    partial_template_name = "catalog/partials/search_results.html"

    def get_template_names(self):
        return [self.partial_template_name if self.request.htmx else self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()[:MAX_QUERY_LENGTH]
        candidates = search(q) if q else []
        prefetch_for_cards([c.part for c in candidates])
        context.update(
            q=q,
            candidates=candidates,
            query_kind=_KIND_LABELS[detect_query_kind(q)] if q else None,
        )
        return context


class PartDetailView(DetailView):
    template_name = "catalog/part_detail.html"
    slug_field = "sku"
    slug_url_kwarg = "sku"
    context_object_name = "part"

    def get_queryset(self):
        return Part.objects.with_related().prefetch_related("offers__supplier")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        alts = alternatives(self.object).select_related("category__parent")[:20]
        alts = prefetch_for_cards(list(alts))
        context.update(alternatives=alts, attribute_rows=self.object.attribute_rows())
        return context
