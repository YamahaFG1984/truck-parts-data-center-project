from urllib.parse import quote

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.sources.models import SourceRecord
from apps.sources.services.standardize import LABELS
from apps.suppliers.models import Supplier

from .models import DecisionLog, Membership, Product, ReviewItem
from .services import export, matching, products, queue, review, search

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ACTIONS = {
    "same": (review.confirm_same, "已确认为同一产品：{code}"),
    "different": (review.mark_different, "已判为不同产品。"),
    "independent": (review.confirm_independent, "已确认为独立产品：{code}"),
    "needs_info": (review.mark_needs_info, "已标记待补充：{code}"),
    "keep": (review.keep_after_key_change, "已保留在 {code}，成员关系恢复。"),
    "split": (review.split_after_key_change, "已处理：该记录现属 {code}。"),
}


class QueueView(TemplateView):
    """Open items grouped into clusters; ?category= ?strength= ?supplier= filter."""

    template_name = "archive/queue.html"

    def get_context_data(self, **kwargs):
        params = self.request.GET
        items = queue.open_items(params.get("category", ""), params.get("strength", ""),
                                 params.get("supplier", ""))
        clusters, singles = queue.clusters(items)
        counts = {c: 0 for c, _ in ReviewItem.Category.choices}
        for category in ReviewItem.objects.filter(status="open").values_list("category",
                                                                             flat=True):
            counts[category] += 1
        return super().get_context_data(**kwargs) | {
            "clusters": clusters, "singles": singles, "params": params,
            "categories": [(c, label, counts[c]) for c, label in ReviewItem.Category.choices],
            "suppliers": Supplier.objects.filter(source_records__isnull=False).distinct(),
            "decided": ReviewItem.objects.exclude(status__in=["open", "superseded"]).count(),
        }


class ItemView(View):
    """Two records side by side (for a key change: new and previous version);
    POST action=same|different|independent|needs_info|keep|split."""

    def get(self, request, pk):
        item = get_object_or_404(ReviewItem.objects.select_related(
            "record_a__supplier", "record_b__supplier", "record_a__source_file",
            "record_b__source_file", "decided_by"), pk=pk)
        sides = (("a", item.record_a),) if item.kind == ReviewItem.Kind.KEY_CHANGE else (
            ("a", item.record_a), ("b", item.record_b))
        members = {side: review.membership_of(record) for side, record in sides if record}
        for membership in members.values():
            membership.size = membership.product.memberships.count()
        return render(request, "archive/item.html", {
            "item": item, "rows": queue.side_by_side(item), "members": members,
            "same_product": len({m.product_id for m in members.values()}) == 1 and len(members) > 1,
            "history": DecisionLog.objects.filter(review_item=item).select_related("actor"),
            "next": _next(request),
        })

    def post(self, request, pk):
        item = get_object_or_404(ReviewItem, pk=pk)
        action = ACTIONS.get(request.POST.get("action", ""))
        if action is None:
            messages.error(request, "未知的动作。")
            return redirect("archive:item", pk=pk)
        function, success = action
        try:
            result = function(item, request.user, request.POST.get("note", "").strip())
        except review.ReviewError as exc:
            messages.error(request, str(exc))
            return redirect("archive:item", pk=pk)
        messages.success(request, success.format(code=getattr(result, "code", "")))
        return redirect(_next(request))


class BulkConfirmView(View):
    def post(self, request):
        ids = [int(i) for i in request.POST.getlist("items") if i.isdigit()]
        items = list(ReviewItem.objects.filter(pk__in=ids, status="open")
                     .select_related("record_a", "record_b"))
        done, refused = review.bulk_confirm(items, request.user)
        if done:
            messages.success(request, f"已批量确认 {len(done)} 条强证据条目，"
                                      "每条都已记入决策日志。")
        for item, reason in refused:
            messages.warning(request, f"条目 #{item.pk} 未确认：{reason}")
        if not ids:
            messages.warning(request, "请先勾选要确认的条目。")
        return redirect(_next(request))


class DetachView(View):
    def post(self, request, pk):
        membership = get_object_or_404(Membership.objects.select_related("product"), pk=pk)
        try:
            product = review.detach(membership, request.user,
                                    request.POST.get("note", "").strip())
        except review.ReviewError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{membership.record_key} 已移出，成为 {product.code}"
                                      "（待核）；相关配对已重新进入待确认。")
        return redirect(_next(request))


class SearchView(TemplateView):
    """?q= any number, keyword, brand or supplier; ?supplier= narrows to one supplier."""

    template_name = "archive/search.html"

    def get_context_data(self, **kwargs):
        params = self.request.GET
        supplier = Supplier.objects.filter(pk=params.get("supplier", "")).first() if (
            params.get("supplier", "").isdigit()) else None
        query = params.get("q", "").strip()
        return super().get_context_data(**kwargs) | {
            "query": query, "supplier": supplier,
            "results": search.search(query, supplier) if query else [],
            "suppliers": Supplier.objects.filter(source_records__isnull=False).distinct(),
            "status_counts": (Product.objects.filter(memberships__isnull=False).distinct()
                              .values("status").annotate(n=Count("id")).order_by("status")),
            "status_labels": dict(Product.Status.choices),
            "open_items": ReviewItem.objects.filter(status="open").count(),
            "exports": export.FILES,
        }


class ProductView(View):
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        if product.merged_into_id:
            messages.info(request, f"{product.code} 已并入 {product.merged_into.code}。")
            return redirect("archive:product", pk=product.merged_into_id)
        members = products.members(product)
        identities = [f"{m.supplier_id}:{m.record_key}" for m in members]
        items = (ReviewItem.objects.filter(Q(identity_a__in=identities)
                                           | Q(identity_b__in=identities))
                 .exclude(status="superseded").select_related("record_a", "record_b")
                 .order_by("status", "-id"))
        return render(request, "archive/product.html", {
            "product": product, "members": members,
            "summary": products.summary(product, members),
            "missing": products.missing(product, members), "items": items,
            "history": _history(product, items),
        })


class RecordView(View):
    """One source record: the whole original row, each field's source, its versions."""

    def get(self, request, pk):
        record = get_object_or_404(SourceRecord.objects.select_related(
            "supplier", "source_file"), pk=pk)
        membership = review.membership_of(record)
        versions, cursor = [], SourceRecord.objects.current().filter(
            supplier=record.supplier, record_key=record.record_key).first()
        while cursor is not None:
            versions.append(cursor)
            cursor = cursor.previous
        return render(request, "archive/record.html", {
            "record": record, "membership": membership, "versions": versions,
            "rows": [{"label": label} | queue.cell(record, name) for name, label in queue.ROWS],
            "raw": [(header, record.cells.get(header, ""), text)
                    for header, text in record.raw.items()],
            "hints": matching.hints(record),
            "missing": [LABELS.get(name, name) for name in record.missing],
            "is_current": versions and versions[0].pk == record.pk,
        })


class ExportView(View):
    def get(self, request, kind):
        if kind not in export.FILES:
            raise Http404
        response = HttpResponse(export.to_bytes(export.BUILDERS[kind]()), content_type=XLSX)
        response["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(export.FILES[kind])}")
        return response


def _history(product, items):
    """Decisions on the product's items, plus product-level actions naming its code."""
    logs = DecisionLog.objects.select_related("actor", "review_item").filter(
        Q(review_item__in=items))
    extra = [log for log in DecisionLog.objects.filter(review_item__isnull=True)
             .select_related("actor")[:500] if product.code in str(log.payload)]
    return sorted({*logs, *extra}, key=lambda log: (log.at, log.pk), reverse=True)


def _next(request) -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}):
        return target
    return reverse("archive:queue")
