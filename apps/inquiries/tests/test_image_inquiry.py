from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.ai.llm.base import LLMError
from apps.ai.llm.mock import MockClient
from apps.ai.schemas import ImageFinding
from apps.catalog.tests.factories import (
    CategoryFactory,
    FitmentFactory,
    PartFactory,
    PartNumberFactory,
)
from apps.inquiries.models import Inquiry
from apps.inquiries.services import image_inquiry
from apps.inquiries.services.image_inquiry import ImageRejected, candidates, prepare_image

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def photo(size=(3000, 2000), fmt="PNG", exif=False) -> bytes:
    image = Image.new("RGB", size, "steelblue")
    out = BytesIO()
    if exif:
        data = image.getexif()
        data[0x010F] = "PhoneMaker"  # Make
        image.save(out, fmt, exif=data)
    else:
        image.save(out, fmt)
    return out.getvalue()


@pytest.fixture
def chamber():
    """The part the mock's photo shows: OE 26570367 (FIT-BCH-00001 in the demo seed)."""
    part = PartFactory(sku="FIT-BCH-00001", name_en="Spring Brake Chamber, T24/30",
                       category=CategoryFactory(name="制动气室", name_en="Spring Brake Chamber"))
    PartNumberFactory(part=part, number="26570367", kind="OE")
    FitmentFactory(part=part, make="Volvo", model="FH12")
    return part


# --- image preparation ---------------------------------------------------------------------------


def test_large_photo_is_shrunk_to_1280_and_reencoded_as_jpeg():
    out = Image.open(BytesIO(prepare_image(photo((3000, 2000)))))

    assert out.format == "JPEG" and max(out.size) == 1280 and out.size == (1280, 853)


def test_small_photo_is_not_upscaled():
    assert Image.open(BytesIO(prepare_image(photo((640, 480))))).size == (640, 480)


def test_exif_is_dropped():
    assert Image.open(BytesIO(photo(fmt="JPEG", exif=True))).getexif()  # the input had it

    assert not Image.open(BytesIO(prepare_image(photo(fmt="JPEG", exif=True)))).getexif()


@pytest.mark.parametrize(("data", "message"), [
    (b"%PDF-1.4 not an image", "无法识别为图片"),
    (b"\x89PNG\r\n\x1a\n broken", "无法识别为图片"),
])
def test_non_images_are_rejected(data, message):
    with pytest.raises(ImageRejected, match=message):
        prepare_image(data)


def test_oversized_upload_is_rejected(monkeypatch):
    monkeypatch.setattr(image_inquiry, "MAX_UPLOAD_MB", 0)

    with pytest.raises(ImageRejected, match="超过"):
        prepare_image(photo((10, 10)))


# --- identification and candidates ---------------------------------------------------------------


def test_upload_reads_the_photo_and_proposes_candidates_without_confirming(admin_client, chamber):
    PartFactory(sku="FIT-BPD-00009")  # unrelated

    response = admin_client.post(
        reverse("inquiries:image"),
        {"photo": SimpleUploadedFile("客户照片.png", photo(), content_type="image/png")},
    )

    inquiry = Inquiry.objects.get()
    assert response.url == reverse("inquiries:detail", args=[inquiry.pk])
    assert inquiry.input_type == "image" and inquiry.image.name.startswith("inquiries/")
    assert inquiry.finding["part_type"] == "spring brake chamber"
    assert inquiry.candidate_part_ids == [chamber.pk]
    assert inquiry.finding["candidates"][0]["match_type"] == "exact"
    assert inquiry.matched_part is None and inquiry.status == "open"
    assert inquiry.ai_task.prompt_name == "image_identify"


def test_the_model_gets_the_compressed_photo_not_the_original(admin_client, chamber, monkeypatch):
    seen = []
    real = MockClient.describe_image

    def spy(self, **kwargs):
        seen.append(kwargs["image_bytes"])
        return real(self, **kwargs)

    monkeypatch.setattr(MockClient, "describe_image", spy)
    original = photo((4000, 3000))

    admin_client.post(reverse("inquiries:image"),
                      {"photo": SimpleUploadedFile("p.png", original, content_type="image/png")})

    sent = Image.open(BytesIO(seen[0]))
    assert seen[0] != original and sent.format == "JPEG" and max(sent.size) == 1280


def test_without_readable_numbers_the_part_type_is_searched(chamber):
    brake_pad = PartFactory(name_en="Brake Pad Set, Front Axle")
    FitmentFactory(part=brake_pad, make="Volvo", model="FH12")

    found = candidates(ImageFinding(part_type="brake pad", visible_numbers=["??????"],
                                    brand_hints=["Volvo"], confidence=0.4))

    assert [c.part for c in found] == [brake_pad] and found[0].match_type == "name"


def test_brand_hint_is_dropped_when_it_finds_nothing(chamber):
    found = candidates(ImageFinding(part_type="spring brake chamber", brand_hints=["Scania"],
                                    confidence=0.4))

    assert [c.part for c in found] == [chamber]


def test_partly_readable_number_still_matches_fuzzily(chamber):
    found = candidates(ImageFinding(part_type="brake chamber", visible_numbers=["265703?7"],
                                    confidence=0.5))

    assert found and found[0].part == chamber


def test_unknown_object_gives_no_candidates(chamber):
    assert candidates(ImageFinding(part_type="unknown", confidence=0.1)) == []


# --- pages and confirmation ----------------------------------------------------------------------


def test_detail_page_marks_demo_mode_and_pending_candidates(admin_client, chamber):
    admin_client.post(reverse("inquiries:image"),
                      {"photo": SimpleUploadedFile("p.png", photo(), content_type="image/png")})
    inquiry = Inquiry.objects.get()

    body = admin_client.get(reverse("inquiries:detail", args=[inquiry.pk])).content.decode()

    assert "演示模式" in body and "待确认" in body and "确认是这个产品" in body
    assert chamber.sku in body and "26570367" in body


def test_non_image_upload_shows_error_and_creates_nothing(admin_client):
    response = admin_client.post(
        reverse("inquiries:image"),
        {"photo": SimpleUploadedFile("x.jpg", b"not really", content_type="image/jpeg")},
    )

    assert response.status_code == 200 and "无法识别为图片" in response.content.decode()
    assert not Inquiry.objects.exists()


def test_confirming_a_candidate_records_it(admin_client, chamber):
    admin_client.post(reverse("inquiries:image"),
                      {"photo": SimpleUploadedFile("p.png", photo(), content_type="image/png")})
    inquiry = Inquiry.objects.get()

    response = admin_client.post(reverse("inquiries:confirm", args=[inquiry.pk]),
                                 {"part": chamber.pk}, follow=True)

    inquiry.refresh_from_db()
    assert (inquiry.matched_part, inquiry.status) == (chamber, "matched")
    assert "已确认为 FIT-BCH-00001" in response.content.decode()


def test_only_proposed_parts_can_be_confirmed(admin_client, chamber):
    admin_client.post(reverse("inquiries:image"),
                      {"photo": SimpleUploadedFile("p.png", photo(), content_type="image/png")})
    inquiry = Inquiry.objects.get()
    stranger = PartFactory()

    response = admin_client.post(reverse("inquiries:confirm", args=[inquiry.pk]),
                                 {"part": stranger.pk}, follow=True)

    inquiry.refresh_from_db()
    assert inquiry.matched_part is None and "只能从候选中确认" in response.content.decode()


def test_model_failure_is_shown_and_can_be_retried(admin_client, chamber, monkeypatch):
    real = MockClient.describe_image

    def down(self, **kwargs):
        raise LLMError("vision endpoint timed out", task=None)

    monkeypatch.setattr(MockClient, "describe_image", down)
    response = admin_client.post(
        reverse("inquiries:image"),
        {"photo": SimpleUploadedFile("p.png", photo(), content_type="image/png")}, follow=True,
    )
    inquiry = Inquiry.objects.get()
    assert "识别失败" in response.content.decode() and "重新识别" in response.content.decode()
    assert inquiry.finding == {"error": "vision endpoint timed out"}

    monkeypatch.setattr(MockClient, "describe_image", real)
    admin_client.post(reverse("inquiries:retry", args=[inquiry.pk]))

    inquiry.refresh_from_db()
    assert inquiry.candidate_part_ids == [chamber.pk] and "error" not in inquiry.finding


def test_admin_page(admin_client):
    assert admin_client.get(reverse("admin:inquiries_inquiry_changelist")).status_code == 200
