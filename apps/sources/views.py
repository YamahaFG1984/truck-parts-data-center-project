from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView

from .forms import UploadForm
from .models import SourceFile
from .services import ingest, intake
from .services.mapping import FIELDS
from .services.readers import ReadError
from .services.storage import DuplicateFile, UploadRejected, store_upload


class FileListView(FormView):
    """Upload a file and see the recent ones."""

    template_name = "sources/file_list.html"
    form_class = UploadForm

    def form_valid(self, form):
        supplier = form.cleaned_data["supplier"]
        try:
            if supplier.pk is None:
                supplier.save()
            source = store_upload(form.cleaned_data["file"], supplier, self.request.user)
        except DuplicateFile as exc:
            messages.warning(self.request, str(exc))
            return redirect("sources:detail", pk=exc.existing.pk)
        except UploadRejected as exc:
            form.add_error("file", str(exc))
            return self.form_invalid(form)
        try:
            intake.inspect(source)
        except ReadError:
            messages.error(self.request, "文件已存档，但无法解析，原因见下方。")
            return redirect("sources:detail", pk=source.pk)
        return redirect("sources:mapping", pk=source.pk)

    def get_context_data(self, **kwargs):
        files = SourceFile.objects.select_related("supplier", "uploaded_by")[:50]
        return super().get_context_data(**kwargs) | {"files": files}


class FileDetailView(DetailView):
    template_name = "sources/file_detail.html"
    context_object_name = "source"
    queryset = SourceFile.objects.select_related("supplier", "uploaded_by")


class OriginalView(View):
    """The archived original, byte for byte, under its original name."""

    def get(self, request, pk):
        source = get_object_or_404(SourceFile, pk=pk)
        return FileResponse(source.file.open("rb"), as_attachment=True,
                            filename=source.original_name)


class MappingView(View):
    template_name = "sources/mapping.html"

    def dispatch(self, request, *args, **kwargs):
        self.source = get_object_or_404(SourceFile.objects.select_related("supplier"),
                                        pk=kwargs["pk"])
        try:
            self.sheets = intake.inspect(self.source)
        except ReadError:
            return redirect("sources:detail", pk=self.source.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk, errors=()):
        return render(request, self.template_name, {
            "source": self.source, "fields": FIELDS, "errors": errors,
            "sheets": intake.suggestions(self.source, self.sheets),
        })

    def post(self, request, pk):
        if self.source.status == SourceFile.Status.COMMITTED:
            messages.error(request, "这份资料已经入库，映射不能再改；如有错误请修正后重新上传。")
            return redirect("sources:detail", pk=pk)
        intake.suggestions(self.source, self.sheets)  # make sure suggestions exist
        chosen = {}
        for key, value in request.POST.items():
            if key.startswith("field__") and value in FIELDS:
                _, i, j = key.split("__")
                chosen[(int(i), int(j))] = value
        errors, warnings = intake.confirm(self.source, chosen, request.user)
        if errors:
            return self.get(request, pk, errors=errors)
        for warning in warnings:
            messages.warning(request, warning)
        messages.success(request, "列映射已确认，并保存为该供应商的模板。")
        return redirect(reverse("sources:preview", args=[pk]))


class PreviewView(View):
    """Every row as it would be stored, with warnings and missing fields; POST commits."""

    template_name = "sources/preview.html"

    def dispatch(self, request, *args, **kwargs):
        self.source = get_object_or_404(SourceFile.objects.select_related("supplier"),
                                        pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        try:
            planned = ingest.preview(self.source)
        except (ingest.IngestError, ReadError) as exc:
            messages.error(request, str(exc))
            return redirect("sources:detail", pk=pk)
        return render(request, self.template_name, {
            "source": self.source, "planned": planned,
            "counts": self.source.stats["preview"],
        })

    def post(self, request, pk):
        try:
            count = ingest.commit(self.source, request.user)
        except (ingest.IngestError, ReadError) as exc:
            messages.error(request, str(exc))
            return redirect("sources:preview" if self.source.mapping.get("confirmed")
                            else "sources:detail", pk=pk)
        messages.success(request, f"已入库 {count} 条来源记录。")
        return redirect("sources:detail", pk=pk)
