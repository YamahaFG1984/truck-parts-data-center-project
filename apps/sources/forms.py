from django import forms

from apps.suppliers.models import Supplier

from .services.storage import MAX_UPLOAD_MB


class UploadForm(forms.Form):
    file = forms.FileField(
        label="资料文件",
        help_text=f"xlsx、csv 或 pdf，不超过 {MAX_UPLOAD_MB} MB。原件会原样存档。",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.csv,.pdf"}),
    )
    supplier = forms.ModelChoiceField(label="供应商", required=False,
                                      queryset=Supplier.objects.order_by("name"))
    new_supplier = forms.CharField(label="或新供应商名称", required=False, max_length=200)

    def clean(self):
        data = super().clean()
        name = (data.get("new_supplier") or "").strip()
        if data.get("supplier") and name:
            raise forms.ValidationError("请选择已有供应商，或填写新供应商名称，二选一。")
        if not data.get("supplier") and not name:
            raise forms.ValidationError("每份资料都要归属一个供应商。")
        if name:
            data["supplier"] = (Supplier.objects.filter(name__iexact=name).first()
                                or Supplier(name=name))
        return data
