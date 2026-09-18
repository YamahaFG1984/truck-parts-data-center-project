"""Suppliers and their price quotes (docs/data-dictionary.html §7)."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Supplier(TimeStampedModel):
    name = models.CharField("名称", max_length=200, unique=True)
    country = models.CharField("国家", max_length=50, default="China", blank=True)
    contact = models.CharField("联系方式", max_length=200, blank=True)
    rating = models.PositiveSmallIntegerField(
        "评级", null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)], help_text="1–5，5 为最好",
    )
    notes = models.TextField("备注", blank=True, help_text="产品线、质量记录等")

    class Meta:
        verbose_name = verbose_name_plural = "供应商"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5),
                name="suppliers_supplier_rating_1_5",
            ),
        ]

    def __str__(self):
        return self.name


class SupplierOffer(TimeStampedModel):
    class PriceTerm(models.TextChoices):
        EXW = "EXW", "EXW 工厂交货"
        FOB = "FOB", "FOB 离岸价"
        CIF = "CIF", "CIF 到岸价"

    supplier = models.ForeignKey(
        Supplier, verbose_name="供应商", on_delete=models.PROTECT, related_name="offers"
    )
    part = models.ForeignKey(
        "catalog.Part", verbose_name="产品", on_delete=models.CASCADE, related_name="offers"
    )
    supplier_pn = models.CharField("供应商料号", max_length=64, blank=True)
    unit_cost_usd = models.DecimalField("单价 USD", max_digits=10, decimal_places=2)
    moq = models.PositiveIntegerField("起订量", null=True, blank=True)
    lead_days = models.PositiveSmallIntegerField("交期（天）", null=True, blank=True)
    price_term = models.CharField(
        "价格条款", max_length=3, choices=PriceTerm.choices, default=PriceTerm.FOB
    )
    quoted_at = models.DateField("报价日期")
    valid_until = models.DateField("有效期至", null=True, blank=True)
    notes = models.TextField("备注", blank=True, help_text="原币种与汇率、质量记录等")

    class Meta:
        verbose_name = verbose_name_plural = "供应商报价"
        # Cheapest first; equal price -> shorter lead time (same rule as best_offer).
        ordering = ["unit_cost_usd", "lead_days", "id"]
        indexes = [models.Index(fields=["part", "unit_cost_usd"], name="suppliers_offer_part_cost")]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "part", "quoted_at"], name="suppliers_offer_unique_per_day"
            ),
            models.CheckConstraint(
                condition=Q(unit_cost_usd__gt=Decimal("0")), name="suppliers_offer_cost_positive"
            ),
            models.CheckConstraint(
                condition=Q(moq__isnull=True) | Q(moq__gt=0), name="suppliers_offer_moq_positive"
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("quoted_at")),
                name="suppliers_offer_valid_after_quote",
            ),
        ]

    def __str__(self):
        return f"{self.supplier} · {self.part.sku} · {self.unit_cost_usd} USD"
