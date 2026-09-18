"""Customer inquiries: what was asked, what the system found, what was confirmed."""

import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


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

    class Meta:
        verbose_name = verbose_name_plural = "询价"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="inquiries_recent"),
            models.Index(fields=["matched_part"], name="inquiries_matched_part"),
        ]

    def __str__(self):
        what = self.raw_input[:40] if self.input_type == self.InputType.TEXT else "照片询价"
        return f"#{self.pk} {what}"

    @property
    def candidate_part_ids(self) -> list[int]:
        return [c["part_id"] for c in self.finding.get("candidates", [])]
