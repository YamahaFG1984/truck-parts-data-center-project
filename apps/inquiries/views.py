import datetime as dt

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.ai.llm.base import LLMError
from apps.suppliers.context_processors import cost_visibility
from apps.suppliers.services.quoting import best_offer

from .forms import PhotoForm, QuoteForm
from .models import Inquiry
from .services.image_inquiry import (
    ImageRejected,
    confirm,
    create_image_inquiry,
    identify,
    stored_candidates,
)
from .services.quoting import QuoteError, build_quote, quote_to_xlsx


def _identify_or_warn(request, inquiry):
    try:
        identify(inquiry)
    except (LLMError, ImproperlyConfigured) as exc:
        if isinstance(exc, ImproperlyConfigured):
            inquiry.finding = {"error": str(exc)}
            inquiry.save(update_fields=["finding", "updated_at"])
        messages.error(request, f"识别失败：{exc}")


class ImageInquiryView(FormView):
    """Upload a customer's photo; the vision model reads it, our matcher searches."""

    template_name = "inquiries/image_upload.html"
    form_class = PhotoForm

    def form_valid(self, form):
        try:
            inquiry = create_image_inquiry(form.cleaned_data["photo"].read(), self.request.user)
        except ImageRejected as exc:
            form.add_error("photo", str(exc))
            return self.form_invalid(form)
        _identify_or_warn(self.request, inquiry)
        return redirect("inquiries:detail", pk=inquiry.pk)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {"mock": settings.LLM_PROVIDER == "mock"}


class InquiryDetailView(DetailView):
    template_name = "inquiries/detail.html"
    context_object_name = "inquiry"
    queryset = Inquiry.objects.select_related("matched_part", "ai_task", "created_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(candidates=stored_candidates(self.object),
                       mock=settings.LLM_PROVIDER == "mock")
        return context


class RetryView(View):
    def post(self, request, pk):
        inquiry = get_object_or_404(Inquiry, pk=pk, input_type=Inquiry.InputType.IMAGE)
        _identify_or_warn(request, inquiry)
        return redirect("inquiries:detail", pk=pk)


class ConfirmView(View):
    def post(self, request, pk):
        inquiry = get_object_or_404(Inquiry, pk=pk)
        part_id = request.POST.get("part", "")
        try:
            part = confirm(inquiry, int(part_id) if part_id.isdigit() else -1)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"已确认为 {part.sku}，记录已更新。")
        return redirect("inquiries:detail", pk=pk)


class InquiryListView(ListView):
    """Every inquiry, newest first; half-typed searches hidden unless ?all=1.

    ?type=text|image  ?hit=yes|no  ?days=7|30
    """

    template_name = "inquiries/list.html"
    context_object_name = "inquiries"
    paginate_by = 50

    def get_queryset(self):
        params = self.request.GET
        qs = Inquiry.objects.all() if params.get("all") else Inquiry.objects.settled()
        qs = qs.select_related("matched_part", "created_by")
        if params.get("type") in Inquiry.InputType.values:
            qs = qs.filter(input_type=params["type"])
        if params.get("hit") == "yes":
            qs = qs.filter(matched_part__isnull=False)
        elif params.get("hit") == "no":
            qs = qs.filter(matched_part__isnull=True)
        if params.get("days", "").isdigit():
            qs = qs.filter(created_at__gte=timezone.now() - dt.timedelta(days=int(params["days"])))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop("page", None)
        context.update(unmatched=Inquiry.objects.unmatched_top(), params=self.request.GET,
                       querystring=query.urlencode())
        return context


class QuoteView(FormView):
    """Add a quote line for the inquiry's product and download the quotation."""

    template_name = "inquiries/quote.html"
    form_class = QuoteForm

    def dispatch(self, request, *args, **kwargs):
        self.inquiry = get_object_or_404(Inquiry.objects.select_related("matched_part"),
                                         pk=kwargs["pk"])
        if self.inquiry.matched_part is None:
            messages.warning(request, "请先确认是哪个产品，再生成报价单。")
            return redirect("inquiries:detail", pk=self.inquiry.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        offer = best_offer(self.inquiry.matched_part)
        return {"qty": (offer.moq if offer and offer.moq else 1),
                "customer": self.inquiry.customer}

    def form_valid(self, form):
        try:
            build_quote(self.inquiry, self.inquiry.matched_part, form.cleaned_data["qty"],
                        form.margin)
        except QuoteError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        if form.cleaned_data["customer"] != self.inquiry.customer:
            self.inquiry.customer = form.cleaned_data["customer"]
            self.inquiry.save(update_fields=["customer", "updated_at"])
        messages.success(self.request, "已加入报价单。")
        return redirect("inquiries:quote", pk=self.inquiry.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lines = list(self.inquiry.quote_lines.select_related("part", "offer__supplier"))
        context.update(inquiry=self.inquiry, lines=lines,
                       total=sum((line.amount_usd for line in lines), start=0))
        return context


class QuoteDownloadView(View):
    def get(self, request, pk):
        inquiry = get_object_or_404(Inquiry, pk=pk)
        if not inquiry.quote_lines.exists():
            messages.warning(request, "报价单还是空的。")
            return redirect("inquiries:quote", pk=pk)
        data = quote_to_xlsx(inquiry, include_costs=cost_visibility(request)["can_view_cost"])
        response = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="quotation-{inquiry.pk}.xlsx"'
        return response
