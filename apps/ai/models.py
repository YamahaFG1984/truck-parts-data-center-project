"""Audit trail of every LLM call (docs/architecture.html §7.4)."""

from django.db import models

from apps.core.models import TimeStampedModel


class AITask(TimeStampedModel):
    """One call to a model. Stores a digest and a short preview of the input, never
    the full prompt, so cost prices or customer data can't pile up in here."""

    class Status(models.TextChoices):
        OK = "ok", "成功"
        INVALID_JSON = "invalid_json", "输出无法解析"
        ERROR = "error", "调用失败"

    prompt_name = models.CharField("提示词", max_length=64, db_index=True)
    provider = models.CharField("提供商", max_length=32)
    model = models.CharField("模型", max_length=100)
    input_digest = models.CharField("输入摘要", max_length=16, help_text="sha256 前 16 位")
    input_preview = models.CharField("输入预览", max_length=500, blank=True)
    has_image = models.BooleanField("含图片", default=False)
    output = models.TextField("输出", blank=True)
    status = models.CharField("状态", max_length=16, choices=Status.choices)
    error = models.TextField("错误", blank=True)
    attempts = models.PositiveSmallIntegerField("尝试次数", default=1)
    prompt_tokens = models.PositiveIntegerField("输入 tokens", default=0)
    completion_tokens = models.PositiveIntegerField("输出 tokens", default=0)
    latency_ms = models.PositiveIntegerField("耗时 ms", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "AI 调用记录"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="ai_task_status_recent")]

    def __str__(self):
        return f"{self.prompt_name} · {self.model} · {self.get_status_display()}"
