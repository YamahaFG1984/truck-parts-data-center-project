"""Archive layer: what we believe the records are (docs/archive-design.html §4.2).

Products and memberships change only through apps/archive/services/review.py, and
every change there is written to DecisionLog. Matching produces ReviewItems only.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Product(TimeStampedModel):
    class Status(models.TextChoices):
        UNREVIEWED = "unreviewed", "待核"
        GROUPED = "grouped", "已确认归一"
        INDEPENDENT = "independent", "已确认独立"

    status = models.CharField("状态", max_length=16, choices=Status.choices,
                              default=Status.UNREVIEWED, db_default=Status.UNREVIEWED)
    needs_info = models.BooleanField("待补充", default=False)
    missing_fields = models.JSONField("待补充字段", default=list, blank=True)
    note = models.TextField("备注", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "归一产品"
        ordering = ["id"]

    def __str__(self):
        return f"{self.code} {self.get_status_display()}"

    @property
    def code(self) -> str:
        return f"P-{self.pk:05d}"


class Membership(TimeStampedModel):
    """"This supplier record belongs to this product", tied to the record's identity
    (supplier + record_key) rather than one version, so a re-sent price keeps it."""

    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        SUSPENDED = "suspended", "暂停（关键字段变化，待复核）"

    product = models.ForeignKey(Product, verbose_name="归一产品", on_delete=models.PROTECT,
                                related_name="memberships")
    supplier = models.ForeignKey("suppliers.Supplier", verbose_name="供应商",
                                 on_delete=models.PROTECT, related_name="+")
    record_key = models.CharField("记录身份", max_length=200)
    current_record = models.ForeignKey("sources.SourceRecord", verbose_name="当前版本",
                                       on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField("状态", max_length=16, choices=Status.choices,
                              default=Status.ACTIVE)
    joined_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="操作人", null=True,
                                  blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = verbose_name_plural = "归一成员"
        constraints = [
            models.UniqueConstraint(fields=["supplier", "record_key"],
                                    name="archive_one_membership_per_identity"),
        ]

    def __str__(self):
        return f"{self.product.code} ← {self.supplier} {self.record_key}"


class ReviewItem(TimeStampedModel):
    """Something a person must decide, with the evidence laid out."""

    class Kind(models.TextChoices):
        PAIR = "pair", "疑似同一产品"
        INCOMPLETE = "incomplete", "待补充"
        KEY_CHANGE = "key_change", "关键字段变化"

    class Category(models.TextChoices):
        STRONG = "strong", "强证据疑似同一产品"
        NO_NUMBER = "no_number", "无编号佐证"
        SAME_SOURCE = "same_source", "同源重复"
        NUMBER_CONFLICT = "number_conflict", "编号冲突"
        POSITION_CONFLICT = "position_conflict", "位置冲突"
        SPEC_CONFLICT = "spec_conflict", "规格冲突"
        INSUFFICIENT = "insufficient", "信息不足"
        INCOMPLETE = "incomplete", "待补充"
        KEY_CHANGE = "key_change", "关键字段变化"

    class Status(models.TextChoices):
        OPEN = "open", "未决"
        SAME = "same", "确认同一"
        DIFFERENT = "different", "判为不同"
        INDEPENDENT = "independent", "确认独立"
        NEEDS_INFO = "needs_info", "待补充"
        SUPERSEDED = "superseded", "证据已变化"

    kind = models.CharField("类型", max_length=16, choices=Kind.choices)
    category = models.CharField("类别", max_length=20, choices=Category.choices)
    strength = models.CharField("强度", max_length=10)
    record_a = models.ForeignKey("sources.SourceRecord", on_delete=models.PROTECT,
                                 related_name="+", verbose_name="记录 A")
    record_b = models.ForeignKey("sources.SourceRecord", on_delete=models.PROTECT,
                                 related_name="+", null=True, blank=True, verbose_name="记录 B")
    identity_a = models.CharField("身份 A", max_length=220)
    identity_b = models.CharField("身份 B", max_length=220, blank=True)
    triggers = models.JSONField("触发原因", default=list)
    agreements = models.JSONField("一致字段", default=list)
    conflicts = models.JSONField("冲突字段", default=list)
    missing = models.JSONField("缺失字段", default=list)
    suggested_action = models.TextField("建议动作")
    evidence_hash = models.CharField("证据哈希", max_length=64)
    rules_version = models.CharField("规则版本", max_length=40)
    status = models.CharField("状态", max_length=16, choices=Status.choices,
                              default=Status.OPEN)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="决定人", null=True,
                                   blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField("决定时间", null=True, blank=True)
    note = models.TextField("说明", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "待确认条目"
        ordering = ["status", "id"]
        indexes = [models.Index(fields=["kind", "identity_a", "identity_b"],
                                name="archive_item_pair")]
        constraints = [
            # At most one undecided item per pair (or per record) and kind.
            models.UniqueConstraint(fields=["kind", "identity_a", "identity_b"],
                                    condition=Q(status="open"), name="archive_one_open_item"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.get_category_display()} {self.identity_a} {self.identity_b}"


class FieldChoice(TimeStampedModel):
    """A person's choice between members' conflicting values for one field."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="choices")
    field = models.CharField("字段", max_length=40)
    record = models.ForeignKey("sources.SourceRecord", on_delete=models.PROTECT,
                               related_name="+", verbose_name="取值来源")
    value = models.JSONField("取值")
    chosen_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    reason = models.TextField("依据")

    class Meta:
        verbose_name = verbose_name_plural = "字段取值决定"
        constraints = [models.UniqueConstraint(fields=["product", "field"],
                                               name="archive_one_choice_per_field")]


class DecisionLog(models.Model):
    """Append-only record of every change to products and memberships."""

    action = models.CharField("动作", max_length=40)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField("时间", auto_now_add=True)
    review_item = models.ForeignKey(ReviewItem, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="decisions")
    payload = models.JSONField("内容", default=dict)

    class Meta:
        verbose_name = verbose_name_plural = "决策日志"
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.action}"
