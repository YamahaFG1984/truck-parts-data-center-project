"""Pydantic shapes for catalog JSON fields (docs/data-dictionary.html §5, §6).

The database stores plain JSON; these models validate it at the edges
(model clean(), importer, AI output) so "anything goes" never reaches the table.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError, model_validator

AttributeType = Literal["number", "enum", "string", "bool"]


class AttributeField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    type: AttributeType
    unit: str | None = None
    required: bool = False
    options: list[str] | None = None

    @model_validator(mode="after")
    def _enum_needs_options(self):
        if self.type == "enum" and not self.options:
            raise ValueError(f"enum field '{self.key}' needs options")
        return self


class AttributeSchema(BaseModel):
    """Category.attribute_schema: which spec keys a product in this category has."""

    model_config = ConfigDict(extra="forbid")

    fields: list[AttributeField] = []

    @model_validator(mode="after")
    def _unique_keys(self):
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("attribute keys must be unique")
        return self

    @property
    def required_keys(self) -> list[str]:
        return [f.key for f in self.fields if f.required]


class Packaging(BaseModel):
    """Part.packaging. Units: cm and kg; missing values stay absent, not zero."""

    model_config = ConfigDict(extra="forbid")

    unit: Literal["pc", "set", "pair", "kit"] | None = None
    pcs_per_carton: PositiveInt | None = None
    carton_l_cm: Decimal | None = Field(default=None, gt=0)
    carton_w_cm: Decimal | None = Field(default=None, gt=0)
    carton_h_cm: Decimal | None = Field(default=None, gt=0)
    gross_weight_kg: Decimal | None = Field(default=None, gt=0)
    net_weight_kg: Decimal | None = Field(default=None, gt=0)
    inner_pack: str | None = None


def validate_attributes(schema: AttributeSchema, values: dict) -> list[str]:
    """Type-check attribute values against a category schema.

    Unknown keys and wrong types are errors. Missing required keys are not:
    incomplete data is allowed in and shows up in the completeness score instead.
    """
    by_key = {f.key: f for f in schema.fields}
    errors = []
    for key, value in values.items():
        field = by_key.get(key)
        if field is None:
            errors.append(f"未定义的属性：{key}")
        elif value is None:
            continue
        elif field.type == "number" and (
            isinstance(value, bool) or not isinstance(value, int | float | Decimal)
        ):
            errors.append(f"{field.label}（{key}）应为数字")
        elif field.type == "enum" and value not in (field.options or []):
            errors.append(f"{field.label}（{key}）取值应为 {field.options} 之一")
        elif field.type == "string" and not isinstance(value, str):
            errors.append(f"{field.label}（{key}）应为文本")
        elif field.type == "bool" and not isinstance(value, bool):
            errors.append(f"{field.label}（{key}）应为是/否")
    return errors


def pydantic_messages(exc: ValidationError) -> list[str]:
    """Flatten a pydantic error into short "field: message" strings for forms."""
    return [f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()]
