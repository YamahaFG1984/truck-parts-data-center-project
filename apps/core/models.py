"""Abstract base models shared by every app.

Concrete models that mix in SourcedModel and declare their own Meta must inherit
from SourcedModel.Meta, otherwise the confidence range constraint is dropped:

    class Meta(SourcedModel.Meta):
        ...
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


class Source(models.TextChoices):
    MANUAL = "manual", "人工"
    IMPORT = "import", "导入"
    AI = "ai", "AI"


class SourcedModel(models.Model):
    """Provenance fields: where a record came from and whether a person confirmed it.

    Priority when sources conflict: verified > manual > import > ai
    (see docs/data-dictionary.html §1). Lower-priority sources only fill blanks.
    """

    source = models.CharField(
        "来源",
        max_length=16,
        choices=Source.choices,
        default=Source.MANUAL,
        db_default=Source.MANUAL,
    )
    confidence = models.DecimalField(
        "置信度",
        max_digits=3,
        decimal_places=2,
        default=Decimal("1.00"),
        db_default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    verified = models.BooleanField("已人工确认", default=False, db_default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="确认人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    verified_at = models.DateTimeField("确认时间", null=True, blank=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="%(app_label)s_%(class)s_confidence_range",
            ),
        ]


class Job(TimeStampedModel):
    """A long operation running on django-q2 (bulk AI enrichment, large imports).

    django-q's own Task row only says done / not done; Job adds the progress the
    page shows (done / failed / total) and where to go when it finishes.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "运行中"
        DONE = "done", "已完成"
        FAILED = "failed", "失败"

    kind = models.CharField("类型", max_length=32)
    title = models.CharField("说明", max_length=200)
    task_id = models.CharField("django-q 任务 ID", max_length=64, blank=True)
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.QUEUED
    )
    total = models.PositiveIntegerField("总数", default=0)
    done = models.PositiveIntegerField("已完成", default=0)
    failed = models.PositiveIntegerField("失败", default=0)
    message = models.TextField("说明", blank=True)
    result_url = models.CharField("结果页", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="发起人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = verbose_name_plural = "后台任务"
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.title} · {self.get_status_display()}"

    @property
    def finished(self) -> bool:
        return self.status in (self.Status.DONE, self.Status.FAILED)

    @property
    def percent(self) -> int:
        if self.finished:
            return 100
        return round(100 * (self.done + self.failed) / self.total) if self.total else 0

    def note(self, line: str) -> None:
        self.message = f"{self.message}\n{line}".strip()
