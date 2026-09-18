from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView
from django.views.generic.base import TemplateResponseMixin

from apps.ai.schemas import STANDARD_FIELDS

from .forms import UploadForm
from .models import ImportBatch, ImportRow
from .services.importing import RESULTS, ImportFailed, dry_run, execute
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
        return reverse("importer:dry_run", args=[self.batch.pk])

    def _context(self, mapping):
        samples = self.table.rows[:3]
        rows = [
            column | {"index": i, "samples": [r.get(column["header"], "") for r in samples]}
            for i, column in enumerate(mapping["columns"])
        ]
        return {"batch": self.batch, "rows": rows, "overwrite": mapping.get("overwrite", False),
                "field_labels": FIELD_LABELS, "steps": STEPS}


RESULT_LABELS = dict(ImportRow.Result.choices)
PROBLEM_RESULTS = ["invalid", "duplicate", "skipped"]
SAMPLE_CHANGES = 20


def _count_cards(counts: dict) -> list[tuple[str, str, int]]:
    return [(key, RESULT_LABELS[key], counts.get(key, 0)) for key in RESULTS]


class DryRunView(TemplateResponseMixin, View):
    """Step 4: what the import will do, row by row, without writing anything."""

    template_name = "importer/dry_run.html"

    def get(self, request, pk):
        batch = get_object_or_404(ImportBatch.objects.select_related("supplier"), pk=pk)
        if not batch.column_mapping.get("columns"):
            messages.info(request, "请先确认列映射。")
            return redirect("importer:mapping", pk=pk)
        if batch.status == ImportBatch.Status.DONE:
            return redirect("importer:result", pk=pk)
        try:
            report = dry_run(batch)
        except (LoaderError, FileNotFoundError) as exc:
            messages.error(request, str(exc) or "文件已不存在。")
            return redirect("importer:preview", pk=pk)
        plans = report.plans
        return self.render_to_response({
            "batch": batch, "steps": STEPS, "cards": _count_cards(report.counts),
            "problems": [p for p in plans if p.result in PROBLEM_RESULTS],
            # Updates first: they say what gets added to parts we already have.
            "changes": sorted(
                (p for p in plans if p.result not in PROBLEM_RESULTS),
                key=lambda p: p.result != "updated",
            )[:SAMPLE_CHANGES],
            "importable": sum(1 for p in plans if p.result in ("new", "updated")),
        })


class ExecuteView(View):
    """POST only: run the import in one transaction."""

    def post(self, request, pk):
        batch = get_object_or_404(ImportBatch, pk=pk)
        if batch.status == ImportBatch.Status.DONE:
            return redirect("importer:result", pk=pk)
        try:
            report = execute(batch)
        except ImportFailed as exc:
            messages.error(request, str(exc))
            return redirect("importer:dry_run", pk=pk)
        counts = report.counts
        messages.success(request, f"导入完成：新增 {counts['new']}，更新 {counts['updated']}。")
        return redirect("importer:result", pk=pk)


class ResultView(DetailView):
    """Step 5: what happened to every row; filter with ?result=."""

    template_name = "importer/result.html"
    context_object_name = "batch"
    queryset = ImportBatch.objects.select_related("supplier")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = self.object.rows.select_related("part").order_by("row_no")
        selected = self.request.GET.get("result")
        if selected in RESULTS:
            rows = rows.filter(result=selected)
        context.update(steps=STEPS, rows=rows, selected=selected,
                       cards=_count_cards(self.object.stats.get("result", {})))
        return context
