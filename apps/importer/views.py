from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView
from django.views.generic.base import TemplateResponseMixin

from apps.ai.schemas import STANDARD_FIELDS

from .forms import UploadForm
from .models import ImportBatch
from .services.loader import LoaderError, read_table
from .services.mapping import FIELD_LABELS, suggest_mapping

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


def _read(batch: ImportBatch):
    with batch.file.open("rb") as fh:
        return read_table(fh, batch.original_name)


class MappingView(TemplateResponseMixin, View):
    """Step 3: confirm which standard field each column holds.

    Suggestions are computed once (synonyms first, the LLM only for leftovers) and
    stored on the batch, so reloading the page never calls the model again.
    """

    template_name = "importer/mapping.html"

    def dispatch(self, request, *args, **kwargs):
        batches = ImportBatch.objects.select_related("supplier")
        self.batch = get_object_or_404(batches, pk=kwargs["pk"])
        try:
            self.table = _read(self.batch)
        except (LoaderError, FileNotFoundError) as exc:
            messages.error(request, str(exc) or "文件已不存在。")
            return redirect("importer:preview", pk=self.batch.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        mapping = self.batch.column_mapping
        if not mapping.get("columns"):
            mapping = {"columns": suggest_mapping(self.table.headers, self.table.rows),
                       "overwrite": False}
            self.batch.column_mapping = mapping
            self.batch.save(update_fields=["column_mapping", "updated_at"])
        return self.render_to_response(self._context(mapping))

    def post(self, request, *args, **kwargs):
        if "reset" in request.POST:
            self.batch.column_mapping = {}
            self.batch.status = ImportBatch.Status.UPLOADED
            self.batch.save(update_fields=["column_mapping", "status", "updated_at"])
            messages.info(request, "已重新生成推荐。")
            return redirect("importer:mapping", pk=self.batch.pk)

        columns = self.batch.column_mapping.get("columns") or suggest_mapping(
            self.table.headers, self.table.rows
        )
        for i, column in enumerate(columns):
            chosen = request.POST.get(f"field_{i}", column["field"])
            if chosen not in STANDARD_FIELDS:
                messages.error(request, f"“{column['header']}”的目标字段无效。")
                return self.render_to_response(self._context(self.batch.column_mapping))
            if chosen != column["field"]:
                column.update(field=chosen, source="manual", confidence=1.0, reason="人工指定")
        self.batch.column_mapping = {"columns": columns, "overwrite": "overwrite" in request.POST}
        self.batch.status = ImportBatch.Status.MAPPED
        self.batch.save(update_fields=["column_mapping", "status", "updated_at"])
        messages.success(request, "列映射已保存。")
        return redirect(self.success_url())

    def success_url(self):
        return reverse("importer:mapping", args=[self.batch.pk])

    def _context(self, mapping):
        samples = self.table.rows[:3]
        rows = [
            column | {"index": i, "samples": [r.get(column["header"], "") for r in samples]}
            for i, column in enumerate(mapping["columns"])
        ]
        return {"batch": self.batch, "rows": rows, "overwrite": mapping.get("overwrite", False),
                "field_labels": FIELD_LABELS, "steps": STEPS}
