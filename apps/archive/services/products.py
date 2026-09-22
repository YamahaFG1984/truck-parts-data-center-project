"""What a product looks like when read (M28): its members' current records, a summary
of the key fields with disagreements marked, and where each value came from.
Read-only; decisions are made in review.py."""

from dataclasses import dataclass, field

from ..models import Membership, Product
from .queue import cell

SUMMARY = [("part_type", "品类"), ("position", "位置"), ("fitment", "适配"),
           ("dims", "尺寸 cm"), ("oe_numbers", "OE / 互换号")]
UNION = {"oe_numbers"}  # suppliers list different numbers for one part: collected, not compared


@dataclass
class Line:
    field: str
    label: str
    values: list = field(default_factory=list)  # [(text, membership)] of active members
    choice: object = None  # FieldChoice

    @property
    def texts(self) -> list[str]:
        seen = []
        for text, _ in self.values:
            for part in (text.split("、") if self.field in UNION else [text]):
                if part and part not in seen:
                    seen.append(part)
        return seen

    @property
    def conflict(self) -> bool:
        return self.field not in UNION and self.choice is None and len(self.texts) > 1

    @property
    def text(self) -> str:
        if self.choice is not None:
            return cell(self.choice.record, self.field)["text"]
        return "、".join(self.texts) if self.field in UNION or not self.conflict else ""


def members(product: Product) -> list[Membership]:
    return list(product.memberships.select_related(
        "supplier", "current_record__source_file", "current_record__supplier")
        .prefetch_related("current_record__numbers").order_by("supplier__name", "record_key"))


def summary(product: Product, memberships: list[Membership]) -> list[Line]:
    choices = {c.field: c for c in product.choices.select_related("record")}
    lines = []
    for name, label in SUMMARY:
        line = Line(name, label, choice=choices.get(name))
        for m in memberships:
            if m.status == Membership.Status.ACTIVE:
                line.values.append((cell(m.current_record, name)["text"], m))
        lines.append(line)
    return lines


def missing(product: Product, memberships: list[Membership]) -> list[str]:
    """Flagged by a person, plus key fields no active member has."""
    from apps.sources.services.standardize import KEY_FIELDS, LABELS

    labels = [LABELS.get(f, f) for f in product.missing_fields]
    active = [m.current_record for m in memberships if m.status == Membership.Status.ACTIVE]
    for name in KEY_FIELDS:
        if active and all(name in r.missing for r in active) and LABELS[name] not in labels:
            labels.append(LABELS[name])
    return labels
