"""Archiving uploaded originals (docs/archive-design.html §5 step 1).

The file is hashed, stored under a uuid name and made read-only on disk. The
same content from the same supplier is refused, so nothing already archived
can be overwritten or silently duplicated.
"""

import hashlib
import os
from pathlib import Path

from django.db import IntegrityError, transaction

from ..models import SourceFile

MAX_UPLOAD_MB = 20
FORMATS = {".xlsx": SourceFile.Format.XLSX, ".csv": SourceFile.Format.CSV,
           ".pdf": SourceFile.Format.PDF}
# Leading bytes each binary format must start with (xlsx is a zip container).
SIGNATURES = {SourceFile.Format.XLSX: b"PK\x03\x04", SourceFile.Format.PDF: b"%PDF-"}


class UploadRejected(ValueError):
    """The upload is refused; the message is shown to the user."""


class DuplicateFile(UploadRejected):
    def __init__(self, existing: SourceFile):
        self.existing = existing
        super().__init__(
            f"该供应商已导入过内容完全相同的文件 #{existing.pk}"
            f"（{existing.original_name}），未重复入库。"
        )


def store_upload(uploaded, supplier, user=None) -> SourceFile:
    """Archive an uploaded file (a Django UploadedFile or File) for a supplier."""
    name = Path(uploaded.name or "").name
    file_format = FORMATS.get(Path(name).suffix.lower())
    if file_format is None:
        raise UploadRejected("只支持 xlsx、csv、pdf 文件。")
    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise UploadRejected(f"文件超过 {MAX_UPLOAD_MB} MB。")

    digest, head = hashlib.sha256(), b""
    for chunk in uploaded.chunks():
        head = head or chunk[:8]
        digest.update(chunk)
    signature = SIGNATURES.get(file_format)
    if signature and not head.startswith(signature):
        raise UploadRejected(f"扩展名是 {Path(name).suffix}，但内容不是 {file_format.label} 文件。")

    sha256 = digest.hexdigest()
    existing = SourceFile.objects.filter(supplier=supplier, sha256=sha256).first()
    if existing:
        raise DuplicateFile(existing)

    source = SourceFile(supplier=supplier, original_name=name[:255], sha256=sha256,
                        size_bytes=uploaded.size, file_format=file_format, uploaded_by=user)
    uploaded.seek(0)
    source.file.save(name, uploaded, save=False)
    try:
        with transaction.atomic():
            source.save()
    except IntegrityError:  # the same file uploaded twice at the same moment
        source.file.delete(save=False)
        raise DuplicateFile(SourceFile.objects.get(supplier=supplier, sha256=sha256)) from None
    _make_read_only(source)
    return source


def _make_read_only(source: SourceFile) -> None:
    try:
        path = source.file.path
    except NotImplementedError:  # non-filesystem storage manages its own permissions
        return
    os.chmod(path, 0o444)
