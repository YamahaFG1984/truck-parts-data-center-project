"""AI enrichment of one part (docs/architecture.html §8.3).

The context holds only public product data: names, category, numbers, fitment,
specs and two reviewed examples of the same category. Cost prices, suppliers and
customers never go to the model.
"""

from decimal import Decimal

from apps.catalog.models import Category, Part

from ..llm.factory import get_client
from ..models import AISuggestion
from ..schemas import EnrichResult

EXAMPLES = 2


def build_context(part: Part) -> dict:
    numbers = list(part.numbers.all())
    examples = (
        Part.objects.reviewed()
        .filter(category_id=part.category_id)
        .exclude(pk=part.pk)
        .exclude(description_en="")
        .order_by("-completeness_score", "sku")[:EXAMPLES]
        if part.category_id else []
    )
    return {
        "sku": part.sku,
        "name_en": part.name_en or "(无)",
        "name_zh": part.name_zh or "(无)",
        "category": part.category.name if part.category_id else "未分类",
        "category_options": sorted(
            Category.objects.filter(parent__isnull=False).values_list("name", flat=True)
        ),
        "attribute_schema": part.category.attribute_schema if part.category_id else {},
        "oe_numbers": [n.number for n in numbers if n.kind == "OE"],
        "cross_numbers": [n.number for n in numbers if n.kind == "CROSS"],
        "fitments": [str(f) for f in part.fitments.all()],
        "attributes": part.attributes,
        "examples": [
            {"name_en": e.name_en, "description_en": e.description_en[:400], "keywords": e.keywords}
            for e in examples
        ],
    }


def enrich_part(part: Part, *, client=None) -> AISuggestion:
    """Ask the model for listing content; the result waits in the review queue.

    Returns the existing pending suggestion instead of calling the model again.
    Raises apps.ai.llm.base.LLMError when the call fails.
    """
    pending = part.suggestions.filter(status=AISuggestion.Status.PENDING).first()
    if pending:
        return pending
    client = client or get_client()
    result, task = client.extract_json(
        prompt_name="enrich_part", variables=build_context(part), schema=EnrichResult
    )
    return AISuggestion.objects.create(
        part=part,
        payload=result.model_dump(),
        confidence=Decimal(str(round(result.confidence, 2))),
        ai_task=task,
    )
