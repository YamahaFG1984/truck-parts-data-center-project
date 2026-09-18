from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import DetailView, FormView

from .forms import UploadForm
from .models import ImportBatch
from .services.loader import LoaderError, read_table

PREVIEW_ROWS = 20
RECENT_BATCHES = 10
STEPS = ["上传", "预览", "列映射", "预检", "结果"]


class UploadView(FormView):
    """Step 1: upload a supplier file; it is parsed once to check it and find the header."""

    template_name = "importer/upload.html"
    form_class = UploadForm

    def form_valid(self, form):
        upload = form.cleaned_data["file"]
        try:
            table = read_table(upload, upload.name)
        except LoaderError as exc:
            form.add_error("file", str(exc))
            return self.form_invalid(form)
        upload.seek(0)
        batch = ImportBatch.objects.create(
            file=upload,
            original_name=upload.name[:255],
            supplier=form.cleaned_data["supplier"],
            header_row=table.header_row,
            stats={"rows": table.row_count, "columns": len(table.headers)},
            created_by=self.request.user,
        )
        messages.success(
            self.request,
            f"已上传，识别到表头在第 {table.header_row} 行，共 {table.row_count} 行数据。",
        )
        return redirect("importer:preview", pk=batch.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recent"] = ImportBatch.objects.select_related("supplier", "created_by")[
            :RECENT_BATCHES
        ]
        context["steps"] = STEPS
        return context


class PreviewView(DetailView):
    """Step 2: show the detected header and the first rows exactly as they will be read."""

    template_name = "importer/preview.html"
    context_object_name = "batch"
    queryset = ImportBatch.objects.select_related("supplier")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["steps"] = STEPS
        batch = self.object
        try:
            with batch.file.open("rb") as fh:
                table = read_table(fh, batch.original_name)
        except (LoaderError, FileNotFoundError) as exc:
            context["error"] = str(exc) or "文件已不存在。"
            return context
        context.update(
            table=table,
            preview=list(zip(table.row_numbers, table.rows, strict=True))[:PREVIEW_ROWS],
            preview_limit=PREVIEW_ROWS,
        )
        return context
