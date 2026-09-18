from pathlib import Path

from django import forms

from apps.suppliers.models import Supplier

from .services.loader import SUPPORTED_EXTENSIONS, XLS_MESSAGE

MAX_UPLOAD_MB = 20


class UploadForm(forms.Form):
    file = forms.FileField(
        label="供应商表格",
        help_text=f".xlsx 或 .csv，不超过 {MAX_UPLOAD_MB} MB。表头可以不在第一行。",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.csv"}),
    )
    supplier = forms.ModelChoiceField(
        label="供应商", queryset=Supplier.objects.order_by("name"), required=False,
        help_text="报价单请选择对应供应商；产品资料可以不选。",
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        suffix = Path(upload.name).suffix.lower()
        if suffix == ".xls":
            raise forms.ValidationError(XLS_MESSAGE)
        if suffix not in SUPPORTED_EXTENSIONS:
            raise forms.ValidationError("只支持 .xlsx 或 .csv 文件。")
        if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"文件超过 {MAX_UPLOAD_MB} MB。")
        return upload
