from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, FormView

from apps.ai.llm.base import LLMError

from .forms import PhotoForm
from .models import Inquiry
from .services.image_inquiry import (
    ImageRejected,
    confirm,
    create_image_inquiry,
    identify,
    stored_candidates,
)


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
