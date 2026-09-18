"""Shapes of structured model output (docs/architecture.html appendix A).

Extra keys from the model are ignored; wrong types or out-of-range values fail
validation, which triggers one retry and then LLMError.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Target fields a supplier column can map to (appendix A.1); M14 reuses this list.
STANDARD_FIELDS = [
    "sku", "oe_number", "cross_number", "supplier_pn", "name_en", "name_zh", "category",
    "brand", "make", "model", "engine", "year_from", "year_to", "unit_cost", "currency", "moq",
    "lead_days", "pcs_per_carton", "carton_l_cm", "carton_w_cm", "carton_h_cm",
    "gross_weight_kg", "net_weight_kg", "image_url", "description_en", "ignore",
]
Confidence = Field(ge=0, le=1)


class _Output(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MappingItem(_Output):
    header: str
    field: str
    confidence: float = Confidence
    reason: str = ""

    @field_validator("field")
    @classmethod
    def _known_field(cls, value):
        if value not in STANDARD_FIELDS:
            raise ValueError(f"unknown field {value!r}")
        return value


class MappingResult(_Output):
    mapping: list[MappingItem]


class FitmentHint(_Output):
    make: str
    model: str | None = None
    engine: str | None = None


class ExtractedRecord(_Output):
    name_en: str | None = None
    name_zh: str | None = None
    oe_numbers: list[str] = []
    cross_numbers: list[str] = []
    supplier_pn: str | None = None
    brand_hints: list[str] = []
    fitment: list[FitmentHint] = []
    unit_cost: float | None = None
    currency: str | None = None
    moq: int | None = None
    lead_days: int | None = None
    notes: str | None = None


class ExtractResult(_Output):
    records: list[ExtractedRecord]


class FAQ(_Output):
    q: str
    a: str


class EnrichResult(_Output):
    title_en: str = Field(max_length=80)
    description_en: str
    keywords: list[str] = []
    selling_points: list[str] = []
    faq: list[FAQ] = []
    category: str | None = None
    attributes: dict = {}
    confidence: float = Confidence


class ImageFinding(_Output):
    part_type: str
    visible_numbers: list[str] = []
    brand_hints: list[str] = []
    description: str = ""
    confidence: float = Confidence
