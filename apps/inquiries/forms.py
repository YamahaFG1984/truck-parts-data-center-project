from django import forms

from .services.image_inquiry import MAX_UPLOAD_MB


class PhotoForm(forms.Form):
    photo = forms.FileField(
        label="零件照片",
        help_text=f"jpg、png 或 webp，不超过 {MAX_UPLOAD_MB} MB。有编号或铭牌的照片识别效果最好。",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp",
                                               "capture": "environment"}),
    )
