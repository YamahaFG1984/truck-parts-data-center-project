"""Customer inquiries: what was asked, what the system found, what was confirmed."""

import datetime as dt
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from apps.core.models import TimeStampedModel

# A typed-ahead search: the same user extends the query within this window.
TYPING_WINDOW = dt.timedelta(seconds=60)


class InquiryQuerySet(models.QuerySet):
    def with_superseded(self):
        """superseded=True when the same user sent a query with the same or a longer key
        (starting with this one) within TYPING_WINDOW: a half-typed or repeated search.
        Only the last row of a typing burst counts as the question."""
        later = Inquiry.objects.filter(
            created_by=OuterRef("created_by"),
            input_type=Inquiry.InputType.TEXT,
            created_at__gt=OuterRef("created_at"),
            created_at__lte=OuterRef("created_at") + TYPING_WINDOW,
            query_key__startswith=OuterRef("query_key"),
        )
        return self.annotate(superseded=Exists(later))

    def settled(self):
        """Inquiries a person actually meant: photos, and text searches not typed over."""
        return self.with_superseded().filter(
            Q(input_type=Inquiry.InputType.IMAGE) | Q(superseded=False)
        )

    def unmatched_top(self, days: int = 30, limit: int = 10):
        """Most frequent settled text searches that found nothing."""
        since = timezone.now() - dt.timedelta(days=days)
        return (
            self.settled()
            .filter(input_type=Inquiry.InputType.TEXT, matched_part__isnull=True,
                    created_at__gte=since)
            .values("query_key")
            .annotate(times=Count("pk"), example=models.Max("raw_input"),
                      last=models.Max("created_at"))
            .order_by("-times", "-last")[:limit]
        )


def inquiry_image_upload_to(instance: "Inquiry", filename: str) -> str:
    """Always JPEG (images are re-encoded on upload), uuid name, never the client's."""
    return f"inquiries/{uuid.uuid4().hex}.jpg"


class Inquiry(TimeStampedModel):
    class InputType(models.TextChoices):
        TEXT = "text", "文字"
        IMAGE = "image", "图片"

    class Status(models.TextChoices):
        OPEN = "open", "待确认"
        MATCHED = "matched", "已确认产品"
        QUOTED = "quoted", "已报价"

    input_type = models.CharField("输入类型", max_length=8, choices=InputType.choices)
    raw_input = models.TextField("原始输入", blank=True, help_text="文字询价的原文；图片询价为空")
    query_key = models.CharField(
        "查询键", max_length=200, blank=True, db_index=True,
        help_text="归一化后的输入，用来统计同一个号的不同写法",
    )
    image = models.ImageField("照片", upload_to=inquiry_image_upload_to, blank=True)
    finding = models.JSONField(
        "识别结果", default=dict, blank=True,
        help_text="AI 读图结果与候选列表；候选只是建议，确认后才写 matched_part",
    )
    ai_task = models.ForeignKey(
        "ai.AITask", verbose_name="AI 调用", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    matched_part = models.ForeignKey(
        "catalog.Part", verbose_name="确认的产品", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="inquiries",
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.OPEN,
        db_default=Status.OPEN,
    )
    customer = models.CharField("客户", max_length=200, blank=True)
    notes = models.TextField("备注", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="询价人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    objects = InquiryQuerySet.as_manager()

    class Meta:
        verbose_name = verbose_name_plural = "询价"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="inquiries_recent"),
            models.Index(fields=["created_by", "input_type", "created_at"],
                         name="inquiries_user_type_time"),
            models.Index(fields=["matched_part"], name="inquiries_matched_part"),
        ]

    def __str__(self):
        what = self.raw_input[:40] if self.input_type == self.InputType.TEXT else "照片询价"
        return f"#{self.pk} {what}"

    @property
    def candidate_part_ids(self) -> list[int]:
        return [c["part_id"] for c in self.finding.get("candidates", [])]


class QuoteLine(TimeStampedModel):
    """One quoted product. Cost, margin and price are snapshots: later offers or
    margin changes never alter a quote already sent."""

    inquiry = models.ForeignKey(Inquiry, verbose_name="询价", on_delete=models.CASCADE,
                                related_name="quote_lines")
    part = models.ForeignKey("catalog.Part", verbose_name="产品", on_delete=models.PROTECT,
                             related_name="+")
    offer = models.ForeignKey("suppliers.SupplierOffer", verbose_name="成本来源报价", null=True,
                              blank=True, on_delete=models.SET_NULL, related_name="+")
    qty = models.PositiveIntegerField("数量")
    unit_cost_usd = models.DecimalField("单位成本 USD", max_digits=10, decimal_places=2)
    margin = models.DecimalField("毛利率", max_digits=4, decimal_places=3)
    unit_price_usd = models.DecimalField("单价 USD", max_digits=10, decimal_places=2)
    note = models.CharField("备注", max_length=200, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "报价行"
        ordering = ["inquiry", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(qty__gt=0), name="inquiries_quote_qty_positive"
            ),
        ]

    def __str__(self):
        return f"{self.part.sku} × {self.qty} @ {self.unit_price_usd}"

    @property
    def amount_usd(self):
        return self.unit_price_usd * self.qty
