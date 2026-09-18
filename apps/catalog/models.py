"""Catalog: the product master data. Field rules live in docs/data-dictionary.html."""

import uuid
from pathlib import Path

from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Coalesce, Lower
from pydantic import ValidationError as PydanticError

from apps.core.models import SourcedModel, TimeStampedModel

from .managers import PartNumberQuerySet, PartQuerySet
from .schemas import AttributeSchema, Packaging, pydantic_messages, validate_attributes
from .services.normalize import normalize_number


class Category(TimeStampedModel):
    name = models.CharField("名称", max_length=100)
    name_en = models.CharField("英文名", max_length=100, blank=True)
    code = models.CharField("SKU 代码", max_length=8, blank=True, help_text="如 BRK，用于生成 SKU")
    parent = models.ForeignKey(
        "self", verbose_name="上级分类", null=True, blank=True,
        on_delete=models.PROTECT, related_name="children",
    )
    attribute_schema = models.JSONField("属性定义", default=dict, db_default={}, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "分类"
        ordering = ["parent__name", "name"]
        constraints = [
            models.UniqueConstraint(
                Coalesce("parent", 0), "name", name="catalog_category_unique_name_per_parent"
            ),
        ]

    def __str__(self):
        return f"{self.parent.name} / {self.name}" if self.parent_id else self.name

    def clean(self):
        try:
            AttributeSchema.model_validate(self.attribute_schema or {})
        except PydanticError as exc:
            raise ValidationError({"attribute_schema": pydantic_messages(exc)}) from exc

    @property
    def schema(self) -> AttributeSchema:
        return AttributeSchema.model_validate(self.attribute_schema or {})


class Brand(TimeStampedModel):
    class Kind(models.TextChoices):
        OEM = "oem", "整车 / 主机厂"
        AFTERMARKET = "aftermarket", "零部件品牌"

    name = models.CharField("品牌", max_length=100)
    kind = models.CharField("类型", max_length=16, choices=Kind.choices, default=Kind.OEM)

    class Meta:
        verbose_name = verbose_name_plural = "品牌"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="catalog_brand_unique_name_ci"),
        ]

    def __str__(self):
        return self.name


class Part(TimeStampedModel, SourcedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        REVIEWED = "reviewed", "已审核"
        PUBLISHED = "published", "已上架"

    sku = models.CharField("SKU", max_length=32, unique=True)
    name_en = models.CharField("英文品名", max_length=200, blank=True)
    name_zh = models.CharField("中文品名", max_length=200, blank=True)
    category = models.ForeignKey(
        Category, verbose_name="分类", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="parts",
    )
    attributes = models.JSONField("规格属性", default=dict, db_default={}, blank=True)
    description_en = models.TextField("英文描述", blank=True)
    keywords = models.JSONField("关键词", default=list, db_default=[], blank=True)
    packaging = models.JSONField("包装", default=dict, db_default={}, blank=True)
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices,
        default=Status.DRAFT, db_default=Status.DRAFT,
    )
    completeness_score = models.PositiveSmallIntegerField("完整度", default=0, db_default=0)
    notes = models.TextField("备注", blank=True)

    objects = PartQuerySet.as_manager()

    class Meta(SourcedModel.Meta):
        verbose_name = verbose_name_plural = "产品"
        ordering = ["sku"]
        indexes = [
            models.Index(fields=["status", "completeness_score"], name="catalog_part_status_score"),
            GinIndex(fields=["name_en"], opclasses=["gin_trgm_ops"], name="catalog_part_name_trgm"),
        ]
        constraints = [
            *SourcedModel.Meta.constraints,
            models.CheckConstraint(
                condition=Q(completeness_score__lte=100), name="catalog_part_score_max_100"
            ),
        ]

    def __str__(self):
        return f"{self.sku} {self.name_en or self.name_zh}".strip()

    def clean(self):
        errors = {}
        try:
            Packaging.model_validate(self.packaging or {})
        except PydanticError as exc:
            errors["packaging"] = pydantic_messages(exc)
        if self.category_id and self.attributes:
            problems = validate_attributes(self.category.schema, self.attributes)
            if problems:
                errors["attributes"] = problems
        if errors:
            raise ValidationError(errors)


class PartNumber(TimeStampedModel, SourcedModel):
    """One identity of a part: an OE number, a cross reference or a supplier number."""

    class Kind(models.TextChoices):
        OE = "OE", "原厂号 OE"
        CROSS = "CROSS", "互换号 Cross"
        SUPPLIER = "SUPPLIER", "供应商料号"

    part = models.ForeignKey(
        Part, verbose_name="产品", on_delete=models.CASCADE, related_name="numbers"
    )
    number = models.CharField("编号原文", max_length=64)
    number_norm = models.CharField("归一化编号", max_length=64, editable=False, db_index=True)
    kind = models.CharField("类型", max_length=16, choices=Kind.choices)
    brand = models.ForeignKey(
        Brand, verbose_name="编号品牌", null=True, blank=True,
        on_delete=models.PROTECT, related_name="numbers",
    )

    objects = PartNumberQuerySet.as_manager()

    class Meta(SourcedModel.Meta):
        verbose_name = verbose_name_plural = "编号"
        ordering = ["kind", "number_norm"]
        indexes = [
            GinIndex(
                fields=["number_norm"], opclasses=["gin_trgm_ops"], name="catalog_pn_norm_trgm"
            ),
        ]
        # The same number may sit on several parts (that is what makes them
        # alternatives); it may not repeat on one part. Two partial constraints
        # because NULL brands never collide in a plain unique index.
        constraints = [
            *SourcedModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["part", "number_norm", "kind", "brand"],
                condition=Q(brand__isnull=False),
                name="catalog_pn_unique_per_part_brand",
            ),
            models.UniqueConstraint(
                fields=["part", "number_norm", "kind"],
                condition=Q(brand__isnull=True),
                name="catalog_pn_unique_per_part_nobrand",
            ),
            models.CheckConstraint(condition=~Q(number_norm=""), name="catalog_pn_norm_not_empty"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}"

    def clean(self):
        if not normalize_number(self.number):
            raise ValidationError({"number": "编号必须包含字母或数字"})

    def save(self, *args, **kwargs):
        self.number = (self.number or "").strip()
        self.number_norm = normalize_number(self.number)
        super().save(*args, **kwargs)


class Fitment(TimeStampedModel, SourcedModel):
    part = models.ForeignKey(
        Part, verbose_name="产品", on_delete=models.CASCADE, related_name="fitments"
    )
    make = models.CharField("品牌", max_length=50)
    model = models.CharField("车系", max_length=50, blank=True)
    engine = models.CharField("发动机", max_length=50, blank=True)
    year_from = models.PositiveSmallIntegerField("起始年份", null=True, blank=True)
    year_to = models.PositiveSmallIntegerField("截止年份", null=True, blank=True)
    notes = models.CharField("备注", max_length=200, blank=True)

    class Meta(SourcedModel.Meta):
        verbose_name = verbose_name_plural = "适配车型"
        ordering = ["make", "model", "year_from"]
        indexes = [models.Index(fields=["make", "model"], name="catalog_fitment_make_model")]
        constraints = [
            *SourcedModel.Meta.constraints,
            models.UniqueConstraint(
                "part", Lower("make"), Lower("model"), Lower("engine"),
                Coalesce("year_from", 0), Coalesce("year_to", 0),
                name="catalog_fitment_unique",
            ),
            models.CheckConstraint(
                condition=Q(year_from__isnull=True)
                | Q(year_to__isnull=True)
                | Q(year_to__gte=F("year_from")),
                name="catalog_fitment_year_order",
            ),
        ]

    def __str__(self):
        years = ""
        if self.year_from or self.year_to:
            years = f"{self.year_from or ''}–{self.year_to or ''}"
        return " ".join(p for p in [self.make, self.model, self.engine, years] if p)


def part_image_upload_to(instance: "PartImage", filename: str) -> str:
    """parts/<sku>/<uuid>.<ext>: never trust the uploaded file name."""
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"parts/{instance.part.sku}/{uuid.uuid4().hex}{ext}"


class PartImage(TimeStampedModel, SourcedModel):
    part = models.ForeignKey(
        Part, verbose_name="产品", on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(
        "图片",
        upload_to=part_image_upload_to,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
    )
    is_primary = models.BooleanField("主图", default=False, db_default=False)
    caption = models.CharField("说明", max_length=200, blank=True)

    class Meta(SourcedModel.Meta):
        verbose_name = verbose_name_plural = "产品图片"
        ordering = ["-is_primary", "id"]
        constraints = [
            *SourcedModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["part"], condition=Q(is_primary=True), name="catalog_image_one_primary"
            ),
        ]

    def __str__(self):
        return f"{self.part.sku} {'主图' if self.is_primary else '图片'}"

    def save(self, *args, **kwargs):
        """The first image of a part becomes primary; a new primary demotes the old one."""
        with transaction.atomic():
            others = PartImage.objects.filter(part_id=self.part_id).exclude(pk=self.pk)
            if not self.is_primary and not others.filter(is_primary=True).exists():
                self.is_primary = True
            if self.is_primary:
                others.filter(is_primary=True).update(is_primary=False)
            super().save(*args, **kwargs)
