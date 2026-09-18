"""Import batches and their row-by-row outcome (docs/architecture.html §7.5)."""

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


def import_upload_to(instance: "ImportBatch", filename: str) -> str:
    """imports/<uuid>.<ext>: the uploaded name is kept only in original_name."""
    return f"imports/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class ImportBatch(TimeStampedModel):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "已上传"
        MAPPED = "mapped", "已映射"
        VALIDATED = "validated", "已预检"
        IMPORTING = "importing", "导入中"
        DONE = "done", "已完成"
        FAILED = "failed", "失败"

    file = models.FileField("文件", upload_to=import_upload_to)
    original_name = models.CharField("原文件名", max_length=255)
    supplier = models.ForeignKey(
        "suppliers.Supplier", verbose_name="供应商", null=True, blank=True,
        on_delete=models.PROTECT, related_name="import_batches",
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices,
        default=Status.UPLOADED, db_default=Status.UPLOADED,
    )
    header_row = models.PositiveIntegerField("表头所在行", null=True, blank=True)
    column_mapping = models.JSONField("列映射", default=dict, db_default={}, blank=True)
    stats = models.JSONField("统计", default=dict, db_default={}, blank=True)
    error = models.TextField("错误信息", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="上传人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = verbose_name_plural = "导入批次"
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.original_name}"


class ImportRow(models.Model):
    """One spreadsheet row and what the import did with it (filled in by M14)."""

    class Result(models.TextChoices):
        NEW = "new", "新增"
        UPDATED = "updated", "更新"
        SKIPPED = "skipped", "跳过"
        DUPLICATE = "duplicate", "疑似重复"
        INVALID = "invalid", "无效"

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_no = models.PositiveIntegerField("表格行号")
    raw = models.JSONField("原始值", default=dict)
    result = models.CharField("结果", max_length=16, choices=Result.choices)
    message = models.TextField("说明", blank=True)
    part = models.ForeignKey(
        "catalog.Part", verbose_name="产品", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = verbose_name_plural = "导入行"
        ordering = ["batch", "row_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_no"], name="importer_row_unique_per_batch"
            ),
        ]

    def __str__(self):
        return f"{self.batch_id}:{self.row_no} {self.get_result_display()}"
