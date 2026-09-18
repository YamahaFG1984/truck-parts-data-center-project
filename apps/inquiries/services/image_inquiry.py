"""Photo inquiry (docs/architecture.html §8.2, fig. A5).

The vision model only reads the photo; every number it reads goes back through
our own matcher. Candidates are suggestions until a person confirms one.
"""

from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.ai.llm.factory import get_client
from apps.ai.schemas import ImageFinding
from apps.catalog.models import Part
from apps.catalog.services.matcher import MAX_RESULTS, Candidate, search

from ..models import Inquiry

MAX_UPLOAD_MB = 10
MAX_SIDE = 1280
JPEG_QUALITY = 85
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}  # MPO: some phone cameras' JPEG variant


class ImageRejected(ValueError):
    """The upload is not an acceptable photo; the message is shown to the user."""


def prepare_image(data: bytes) -> bytes:
    """Verify, fix phone rotation, shrink to MAX_SIDE and re-encode as JPEG.

    Re-encoding also drops EXIF (phone photos often carry GPS). The model and the
    stored file both get this version, never the original upload.
    """
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ImageRejected(f"图片超过 {MAX_UPLOAD_MB} MB。")
    try:
        with Image.open(BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageRejected("无法识别为图片，请上传 jpg、png 或 webp。") from exc
    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected(f"不支持的图片格式 {fmt}，请上传 jpg、png 或 webp。")

    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = BytesIO()
    image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def create_image_inquiry(data: bytes, user) -> Inquiry:
    compressed = prepare_image(data)
    inquiry = Inquiry(input_type=Inquiry.InputType.IMAGE, created_by=user)
    inquiry.image.save("photo.jpg", ContentFile(compressed), save=True)
    return inquiry


def identify(inquiry: Inquiry, *, client=None) -> Inquiry:
    """Ask the vision model about the photo and store the finding plus candidates.

    On failure the error is stored in finding["error"] and apps.ai LLMError is raised.
    """
    from apps.ai.llm.base import LLMError

    client = client or get_client()
    with inquiry.image.open("rb") as fh:
        image_bytes = fh.read()
    try:
        finding, task = client.describe_image(
            prompt_name="image_identify", image_bytes=image_bytes, schema=ImageFinding
        )
    except LLMError as exc:
        inquiry.finding = {"error": str(exc)}
        inquiry.ai_task = exc.task
        inquiry.save(update_fields=["finding", "ai_task", "updated_at"])
        raise
    found = candidates(finding)
    inquiry.finding = finding.model_dump() | {
        "candidates": [
            {"part_id": c.part.pk, "match_type": c.match_type, "score": c.score,
             "matched_number": c.matched_number, "matched_kind": c.matched_kind}
            for c in found
        ]
    }
    inquiry.ai_task = task
    inquiry.matched_part = None  # nothing is confirmed by the machine
    inquiry.status = Inquiry.Status.OPEN
    inquiry.save(update_fields=["finding", "ai_task", "matched_part", "status", "updated_at"])
    return inquiry


def candidates(finding: ImageFinding, limit: int = MAX_RESULTS) -> list[Candidate]:
    """Every readable number through the matcher; without numbers, search by part type
    (with brand hints first, then without). Best candidate per part, best first."""
    found: list[Candidate] = []
    for number in finding.visible_numbers:
        readable = number.replace("?", "").strip()
        if readable:
            found += search(f"oe:{readable}")
    if not found and finding.part_type and finding.part_type != "unknown":
        for brand in [*finding.brand_hints[:1], ""]:
            found = search(f"name:{finding.part_type} {brand}".strip())
            if found:
                break
    best: dict[int, Candidate] = {}
    for c in found:
        if c.part.pk not in best or c.sort_key < best[c.part.pk].sort_key:
            best[c.part.pk] = c
    return sorted(best.values(), key=lambda c: c.sort_key)[:limit]


def stored_candidates(inquiry: Inquiry) -> list[Candidate]:
    """Rebuild Candidate objects from finding["candidates"] for display (one query)."""
    from apps.catalog.managers import prefetch_for_cards

    rows = inquiry.finding.get("candidates", [])
    parts = Part.objects.select_related("category__parent").in_bulk([r["part_id"] for r in rows])
    result = [
        Candidate(parts[r["part_id"]], r["match_type"], r["score"], r.get("matched_number"),
                  r.get("matched_kind"))
        for r in rows if r["part_id"] in parts
    ]
    prefetch_for_cards([c.part for c in result])
    return result


def confirm(inquiry: Inquiry, part_id: int) -> Part:
    """Record the person's choice; only a part the system proposed can be confirmed."""
    if part_id not in inquiry.candidate_part_ids:
        raise ValueError("只能从候选中确认产品。")
    inquiry.matched_part = Part.objects.get(pk=part_id)
    inquiry.status = Inquiry.Status.MATCHED
    inquiry.save(update_fields=["matched_part", "status", "updated_at"])
    return inquiry.matched_part
