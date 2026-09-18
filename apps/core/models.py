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
