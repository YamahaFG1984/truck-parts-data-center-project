"""Source layer: original files and the records extracted from them
(docs/archive-design.html §4.1).

Nothing in this app is ever edited after it is written. A supplier sending the
same record again produces a new SourceRecord version linked by `previous`;
the original file is stored read-only and kept even when parsing fails.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.services.normalize import normalize_number
from apps.core.models import TimeStampedModel


def source_upload_to(instance: "SourceFile", filename: str) -> str:
    """sources/<uuid>.<ext>: the uploaded name is kept only in original_name."""
    return f"sources/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class SourceFile(TimeStampedModel):
    class Format(models.TextChoices):
        XLSX = "xlsx", "Excel"
        CSV = "csv", "CSV"
        PDF = "pdf", "PDF"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "已上传"
        MAPPED = "mapped", "已确认映射"
        PREVIEWED = "previewed", "已预检"
        COMMITTED = "committed", "已入库"
        FAILED = "failed", "解析失败"

    supplier = models.ForeignKey(
        "suppliers.Supplier", verbose_name="供应商", on_delete=models.PROTECT,
        related_name="source_files",
    )
    file = models.FileField("原件", upload_to=source_upload_to)
    original_name = models.CharField("原文件名", max_length=255)
    sha256 = models.CharField("SHA-256", max_length=64, db_index=True)
    size_bytes = models.PositiveBigIntegerField("大小（字节）")
    file_format = models.CharField("格式", max_length=8, choices=Format.choices)
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices,
        default=Status.UPLOADED, db_default=Status.UPLOADED,
    )
    mapping = models.JSONField("列映射", default=dict, db_default={}, blank=True)
    stats = models.JSONField("统计", default=dict, db_default={}, blank=True)
    error = models.TextField("失败原因", blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="上传人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = verbose_name_plural = "资料文件"
        ordering = ["-created_at"]
        constraints = [
            # The same file from the same supplier is imported once; re-sending
            # it cannot overwrite or duplicate what is already archived.
            models.UniqueConstraint(fields=["supplier", "sha256"],
                                    name="sources_file_unique_per_supplier"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.original_name}"


class ImmutableRecord(Exception):
    """Raised on any attempt to change or delete a written SourceRecord."""


class SourceRecordQuerySet(models.QuerySet):
    def current(self):
        """The latest version of every record (no newer version points back at it)."""
        return self.filter(next_version__isnull=True)

    def update(self, **kwargs):
        raise ImmutableRecord("来源记录写入后不可修改；更新请写入新版本。")

    def delete(self):
        raise ImmutableRecord("来源记录不可删除。")


class SourceRecord(models.Model):
    """One extracted row. Written once, never changed."""

    class KeyKind(models.TextChoices):
        SOURCE_ID = "source_id", "源记录 ID"
        SUPPLIER_SKU = "supplier_sku", "供应商料号"
        CONTENT = "content", "内容哈希（无稳定键）"

    class ChangeType(models.TextChoices):
        NEW = "new", "新增"
        PRICE_UPDATE = "price_update", "报价更新"
        INFO_UPDATE = "info_update", "资料更新（非关键字段）"
        KEY_CHANGE = "key_change", "关键字段变化"
        RESTANDARDIZE = "restandardize", "规则重算"

    source_file = models.ForeignKey(SourceFile, verbose_name="资料文件",
                                    on_delete=models.PROTECT, related_name="records")
    supplier = models.ForeignKey("suppliers.Supplier", verbose_name="供应商",
                                 on_delete=models.PROTECT, related_name="source_records")
    record_key = models.CharField("记录身份", max_length=200,
                                  help_text="同一供应商内识别\"同一条记录\"的键")
    key_kind = models.CharField("身份来源", max_length=16, choices=KeyKind.choices)
    version = models.PositiveIntegerField("版本", default=1)
    previous = models.OneToOneField(
        "self", verbose_name="上一版本", null=True, blank=True,
        on_delete=models.PROTECT, related_name="next_version",
    )
    change_type = models.CharField("变化类型", max_length=16, choices=ChangeType.choices,
                                   default=ChangeType.NEW)
    note = models.CharField("版本说明", max_length=200, blank=True,
                            help_text="规则重算时记下规则版本与变化字段")

    # Where in the original file: Excel sheet + row, or PDF page + table + row.
    locator = models.CharField("定位", max_length=120, help_text="如 Sheet1!R12 或 P3/T1/R5")
    sheet = models.CharField("工作表", max_length=100, blank=True)
    page = models.PositiveIntegerField("页码", null=True, blank=True)
    table_no = models.PositiveIntegerField("表序号", null=True, blank=True)
    row_no = models.PositiveIntegerField("行号")

    raw = models.JSONField("原文", default=dict, help_text="原表头 → 单元格原文")
    cells = models.JSONField("单元格", default=dict, help_text="原表头 → 单元格坐标")
    fields = models.JSONField("标准字段", default=dict,
                              help_text="字段 → 值、原文、列、单元格、规则、警告")
    warnings = models.JSONField("警告", default=list, blank=True)
    missing = models.JSONField("缺失字段", default=list, blank=True)
    content_hash = models.CharField("内容哈希", max_length=64)

    # Typed copies of standardized fields, for querying and matching (M24 fills them).
    supplier_sku = models.CharField("供应商料号", max_length=100, blank=True)
    name = models.CharField("原始名称", max_length=300, blank=True)
    part_type = models.CharField("品类", max_length=100, blank=True)
    position = models.CharField("位置", max_length=20, blank=True)
    make = models.CharField("适配品牌", max_length=60, blank=True)
    model = models.CharField("适配车型", max_length=100, blank=True)
    year_from = models.PositiveSmallIntegerField("起始年份", null=True, blank=True)
    year_to = models.PositiveSmallIntegerField("截止年份", null=True, blank=True)
    dim_l_cm = models.DecimalField("长 cm", max_digits=8, decimal_places=2, null=True, blank=True)
    dim_w_cm = models.DecimalField("宽 cm", max_digits=8, decimal_places=2, null=True, blank=True)
    dim_h_cm = models.DecimalField("高 cm", max_digits=8, decimal_places=2, null=True, blank=True)
    price = models.DecimalField("单价", max_digits=14, decimal_places=4, null=True, blank=True)
    currency = models.CharField("币种", max_length=3, blank=True, help_text="原样保留，不换算")
    moq = models.PositiveIntegerField("MOQ", null=True, blank=True)
    quote_date = models.DateField("报价日期", null=True, blank=True)

    created_at = models.DateTimeField("写入时间", auto_now_add=True)

    objects = SourceRecordQuerySet.as_manager()

    class Meta:
        verbose_name = verbose_name_plural = "来源记录"
        ordering = ["source_file", "row_no"]
        indexes = [
            models.Index(fields=["supplier", "record_key"], name="sources_record_identity"),
            models.Index(fields=["part_type", "make", "model"], name="sources_record_block"),
        ]
        constraints = [
            # A rule rerun re-reads the same row of the same file into a new version.
            models.UniqueConstraint(fields=["source_file", "locator", "version"],
                                    name="sources_record_unique_locator"),
            models.CheckConstraint(
                condition=Q(previous__isnull=True) | Q(version__gt=1),
                name="sources_record_version_after_first",
            ),
        ]

    def __str__(self):
        return f"{self.supplier} {self.record_key} v{self.version}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecord("来源记录写入后不可修改；更新请写入新版本。")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecord("来源记录不可删除。")


class RecordNumberQuerySet(models.QuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.normalize()
        return super().bulk_create(objs, *args, **kwargs)


class RecordNumber(models.Model):
    """Number index of a record, for search and candidate recall."""

    class Kind(models.TextChoices):
        SUPPLIER_SKU = "supplier_sku", "供应商料号"
        OE = "oe", "OE / 互换号"
        SOURCE_ID = "source_id", "源记录 ID"

    record = models.ForeignKey(SourceRecord, verbose_name="来源记录",
                               on_delete=models.CASCADE, related_name="numbers")
    kind = models.CharField("类型", max_length=16, choices=Kind.choices)
    number = models.CharField("编号原文", max_length=100)
    number_norm = models.CharField("归一化编号", max_length=100, db_index=True, editable=False)

    objects = RecordNumberQuerySet.as_manager()

    class Meta:
        verbose_name = verbose_name_plural = "来源编号"
        constraints = [
            models.UniqueConstraint(fields=["record", "kind", "number_norm"],
                                    name="sources_number_unique_per_record"),
            models.CheckConstraint(condition=~Q(number_norm=""),
                                   name="sources_number_norm_not_empty"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}"

    def normalize(self):
        self.number = (self.number or "").strip()
        self.number_norm = normalize_number(self.number)

    def save(self, *args, **kwargs):
        self.normalize()
        super().save(*args, **kwargs)


class MappingTemplate(TimeStampedModel):
    """A column mapping a person confirmed, reused for the supplier's next file
    with the same headers."""

    supplier = models.ForeignKey("suppliers.Supplier", verbose_name="供应商",
                                 on_delete=models.CASCADE, related_name="mapping_templates")
    header_signature = models.CharField("表头签名", max_length=64)
    headers = models.JSONField("表头", default=list)
    columns = models.JSONField("列映射", default=list)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="确认人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = verbose_name_plural = "列映射模板"
        constraints = [
            models.UniqueConstraint(fields=["supplier", "header_signature"],
                                    name="sources_template_unique_per_supplier"),
        ]

    def __str__(self):
        return f"{self.supplier} · {len(self.headers)} 列"
