from decimal import Decimal

from django import forms
from django.conf import settings

from .services.image_inquiry import MAX_UPLOAD_MB


class PhotoForm(forms.Form):
    photo = forms.FileField(
        label="零件照片",
        help_text=f"jpg、png 或 webp，不超过 {MAX_UPLOAD_MB} MB。有编号或铭牌的照片识别效果最好。",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp",
                                               "capture": "environment"}),
    )


class QuoteForm(forms.Form):
    qty = forms.IntegerField(label="数量", min_value=1, max_value=1_000_000)
    margin_percent = forms.DecimalField(
        label="目标毛利 %", min_value=Decimal("0"), max_value=Decimal("999"), decimal_places=2,
        help_text="售价 = 最低成本 × (1 + 毛利)",
    )
    customer = forms.CharField(label="客户", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("margin_percent", settings.DEFAULT_MARGIN * 100)
        super().__init__(*args, **kwargs)

    @property
    def margin(self) -> Decimal:
        return self.cleaned_data["margin_percent"] / 100
