"""Audit trail of LLM calls and reviewable AI suggestions (docs/architecture.html §7.4, §8.3)."""

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.models import Source, TimeStampedModel


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


# Suggestion payload key -> (Part field, label). Order is the review screen order.
SUGGESTION_FIELDS = {
    "title_en": ("title_en", "上架标题"),
    "description_en": ("description_en", "英文描述"),
    "keywords": ("keywords", "关键词"),
    "selling_points": ("selling_points", "卖点"),
    "faq": ("faq", "FAQ"),
    "category": ("category", "分类"),
    "attributes": ("attributes", "规格属性"),
}


class AISuggestion(TimeStampedModel):
    """AI-generated content for one part, waiting for a person.

    accept() is the only path by which AI output reaches catalog fields; nothing
    else in the project sets a part's source to "ai".
    """

    class Status(models.TextChoices):
        PENDING = "pending", "待审核"
        ACCEPTED = "accepted", "已采纳"
        REJECTED = "rejected", "已拒绝"

    part = models.ForeignKey(
        "catalog.Part", verbose_name="产品", on_delete=models.CASCADE, related_name="suggestions"
    )
    payload = models.JSONField("建议内容")
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices,
        default=Status.PENDING, db_default=Status.PENDING,
    )
    confidence = models.DecimalField("置信度", max_digits=3, decimal_places=2, default=Decimal("0"))
    ai_task = models.ForeignKey(
        AITask, verbose_name="AI 调用", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="suggestions",
    )
    accepted_fields = models.JSONField("采纳的字段", default=list, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="审核人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    reason = models.TextField("拒绝原因 / 审核说明", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "AI 建议"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="ai_suggestion_queue")]

    def __str__(self):
        return f"{self.part.sku} · {self.get_status_display()}"

    # --- review ----------------------------------------------------------------------------

    def rows(self) -> list[dict]:
        """Current value vs suggested value per field, for the review screen."""
        part = self.part
        category = self._category()
        rows = []
        for key, (field, label) in SUGGESTION_FIELDS.items():
            suggested = self.payload.get(key)
            if key == "category":
                current = part.category.name if part.category_id else ""
                applicable, why = category is not None, "" if category else "分类不在分类树中"
            elif key == "attributes":
                current, suggested = part.attributes, self._clean_attributes()
                applicable, why = bool(suggested), "" if suggested else "没有可用的规格值"
            else:
                current = getattr(part, field)
                applicable, why = bool(suggested), ""
            has_value = current not in ("", [], {}, None)
            if applicable and part.verified and has_value and key != "attributes":
                applicable, why = False, "产品已人工确认，已有值不覆盖"
            # Filling a blank is ticked by default; replacing a value needs a deliberate tick.
            replaces = applicable and key != "attributes" and current not in ("", [], {}, None)
            if replaces and not why:
                why = "会覆盖当前值，确认无误再勾选"
            rows.append({"key": key, "label": label, "current": current, "suggested": suggested,
                         "applicable": applicable, "replaces": replaces, "why": why})
        return rows

    @transaction.atomic
    def accept(self, user, fields: list[str]) -> list[str]:
        """Write the chosen fields to the part; returns the fields actually applied."""
        from apps.catalog.services.quality import recompute

        if self.status != self.Status.PENDING:
            raise ValueError("这条建议已经审核过了。")
        # Re-read and lock the part: someone may have edited it since the page loaded,
        # and merging into a stale copy would silently undo their change.
        # of=("self",): PostgreSQL can't lock the nullable side of the category join.
        part = (
            type(self.part).objects.select_for_update(of=("self",))
            .select_related("category").get(pk=self.part_id)
        )
        self.part = part
        applicable = {row["key"]: row for row in self.rows() if row["applicable"]}
        applied = []
        for key in fields:
            if key not in applicable:
                continue
            if key == "category":
                part.category = self._category()
            elif key == "attributes":
                part.attributes = self._clean_attributes() | {
                    k: v for k, v in part.attributes.items() if v is not None
                }
            else:
                setattr(part, SUGGESTION_FIELDS[key][0], self.payload[key])
            applied.append(key)
        if applied:
            labels = "、".join(SUGGESTION_FIELDS[k][1] for k in applied)
            stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
            part.notes = (part.notes + "\n" if part.notes else "") + (
                f"[AI 补全 #{self.pk}] 采纳：{labels}；审核人 {user}；{stamp}"
            )
            part.source = Source.AI
            part.confidence = min(part.confidence, self.confidence)
            part.save()
            recompute(type(part).objects.filter(pk=part.pk))
        self.status = self.Status.ACCEPTED
        self.accepted_fields = applied
        self.reviewed_by, self.reviewed_at = user, timezone.now()
        self.save(update_fields=["status", "accepted_fields", "reviewed_by", "reviewed_at",
                                 "updated_at"])
        return applied

    def reject(self, user, reason: str) -> None:
        if self.status != self.Status.PENDING:
            raise ValueError("这条建议已经审核过了。")
        if not reason.strip():
            raise ValueError("请写明拒绝原因，它会用来改进提示词。")
        self.status = self.Status.REJECTED
        self.reason = reason.strip()
        self.reviewed_by, self.reviewed_at = user, timezone.now()
        self.save(update_fields=["status", "reason", "reviewed_by", "reviewed_at", "updated_at"])

    def _category(self):
        from apps.catalog.models import Category

        name = (self.payload.get("category") or "").strip()
        if not name:
            return None
        return (
            Category.objects.filter(models.Q(name__iexact=name) | models.Q(name_en__iexact=name))
            .order_by("-parent_id")
            .first()
        )

    def _clean_attributes(self) -> dict:
        """Suggested spec values that fit the part's category schema; others are dropped.
        Only keys the part doesn't already have: AI never replaces a spec value."""
        from apps.catalog.schemas import validate_attributes

        part = self.part
        category = part.category or self._category()
        if category is None:
            return {}
        schema = category.schema
        known = {f.key for f in schema.fields}
        suggested = self.payload.get("attributes") or {}
        return {
            key: value for key, value in suggested.items()
            if key in known and value is not None and part.attributes.get(key) is None
            and not validate_attributes(schema, {key: value})
        }
