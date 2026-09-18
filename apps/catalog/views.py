from django.contrib import messages
from django.db.models import Prefetch
from django.views.generic import DetailView, ListView, TemplateView

from .managers import prefetch_for_cards
from .models import Category, Part, PartImage
from .services.matcher import alternatives, search
from .services.normalize import detect_query_kind
from .services.quality import MISSING_LABELS

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
        inquiry = None
        if q:
            # Figure A2: every search is logged as an inquiry (one INSERT). Imported at
            # run time: inquiries depends on catalog, catalog never imports inquiries.
            from apps.inquiries.services.logging import log_text_search

            inquiry = log_text_search(q, candidates, self.request.user)
        prefetch_for_cards([c.part for c in candidates])
        context.update(
            q=q,
            candidates=candidates,
            inquiry=inquiry,
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
        context.update(
            alternatives=alts,
            attribute_rows=self.object.attribute_rows(),
            # ai.AISuggestion via its related_name: catalog does not import the ai app.
            pending_suggestion=self.object.suggestions.filter(status="pending")
            .select_related("ai_task").first(),
        )
        return context


class PartListView(ListView):
    """Filtered part list: the dashboard's drill-down target.

    ?missing=<item>  one of MISSING_LABELS    ?score=40-70  completeness range
    ?status=draft|reviewed|published          ?category=<id>
    """

    template_name = "catalog/part_list.html"
    context_object_name = "parts"
    paginate_by = 50

    def get_queryset(self):
        params = self.request.GET
        self.filters = []
        primary = PartImage.objects.filter(is_primary=True)
        qs = (
            Part.objects.select_related("category__parent")
            .prefetch_related(Prefetch("images", queryset=primary, to_attr="primary_images"))
            .order_by("completeness_score", "sku")
        )

        missing = params.get("missing")
        if missing in MISSING_LABELS:
            qs = qs.missing(missing)
            self.filters.append(("missing", MISSING_LABELS[missing]))
        elif missing:
            messages.warning(self.request, f"未知的筛选项“{missing}”，已忽略。")

        low, _, high = params.get("score", "").partition("-")
        if low.isdigit() and high.isdigit():
            qs = qs.filter(completeness_score__gte=int(low), completeness_score__lte=int(high))
            self.filters.append(("score", f"完整度 {low}–{high}"))

        status = params.get("status")
        if status in Part.Status.values:
            qs = qs.filter(status=status)
            self.filters.append(("status", Part.Status(status).label))

        category = params.get("category")
        if category and category.isdigit():
            qs = qs.filter(category_id=int(category))
            name = Category.objects.filter(pk=int(category)).values_list("name", flat=True).first()
            self.filters.append(("category", f"分类 {name or category}"))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop("page", None)
        context.update(filters=self.filters, querystring=query.urlencode())
        return context
