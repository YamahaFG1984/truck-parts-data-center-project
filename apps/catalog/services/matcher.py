"""Three-level part matching (docs/architecture.html §7.2).

    L1 exact / normalized   number_norm == query
    L2 prefix / contains    suffix variants: "20443906-1", "A0004201520/2", "volvo 20443906"
    L3 fuzzy                pg_trgm similarity >= FUZZY_THRESHOLD (difflib on SQLite)
    text queries            tokens against names, category and fitment

Matching only ever looks at our own database; nothing here asks an LLM to guess.
If L1 finds exactly one part the lower levels are skipped entirely.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Literal

from django.db import connection
from django.db.models import CharField, F, Q, QuerySet, Value
from django.db.models.functions import Length

from ..models import Part, PartNumber
from .normalize import (
    canonical_brand,
    detect_query_kind,
    normalize_number,
    split_query_prefix,
)

MAX_RESULTS = 20
FUZZY_THRESHOLD = 0.45  # pg_trgm similarity; one wrong digit in 7 scores ~0.45
FALLBACK_THRESHOLD = 0.75  # difflib ratio used on SQLite, where pg_trgm is missing
NAME_THRESHOLD = 0.3  # pg_trgm word similarity for misspelled names
MIN_CONTAINED_LEN = 5  # shortest number allowed to match "inside" another
POOL_LIMIT = 2000  # rows the SQLite fuzzy fallback scores in Python

MatchType = Literal["exact", "normalized", "prefix", "fuzzy", "name"]
_PRIORITY = {"exact": 0, "normalized": 1, "prefix": 2, "fuzzy": 3, "name": 4}
_MATCH_KINDS = ["OE", "CROSS"]  # identities that make two parts alternatives


@dataclass(frozen=True)
class Candidate:
    part: Part
    match_type: MatchType
    score: float
    matched_number: str | None = None
    matched_kind: str | None = None

    @property
    def sort_key(self):
        part = self.part
        return (_PRIORITY[self.match_type], -self.score, -part.completeness_score, part.sku)


def search(raw: str | None, *, limit: int = MAX_RESULTS) -> list[Candidate]:
    """Best candidates for a search-box input, best first, at most one per part."""
    _, text = split_query_prefix(raw)
    kind = detect_query_kind(raw)
    norm = normalize_number(text)
    if not norm and not text.strip():
        return []

    if kind == "sku":
        return _by_sku(text, limit)
    if kind == "text":
        return _by_name(text, limit)

    found = _exact(_as_typed(raw), norm)
    if len({c.part.pk for c in found}) == 1:
        return _best_per_part(found)
    if len(found) < limit:
        found += _prefix(norm, limit)
    if len(_best_per_part(found)) < limit:
        found += _fuzzy(norm, limit)
    return _best_per_part(found)[:limit]


def alternatives(part: Part) -> QuerySet[Part]:
    """Other parts sharing any OE or cross number with this one (one query)."""
    numbers = PartNumber.objects.filter(part=part, kind__in=_MATCH_KINDS).values("number_norm")
    return (
        Part.objects.filter(numbers__number_norm__in=numbers, numbers__kind__in=_MATCH_KINDS)
        .exclude(pk=part.pk)
        .distinct()
        .order_by("-completeness_score", "sku")
    )


# --- levels ------------------------------------------------------------------------


def _candidate(pn: PartNumber, match_type: MatchType, score: float) -> Candidate:
    return Candidate(pn.part, match_type, round(score, 3), pn.number, pn.kind)


_TYPED_PREFIX = re.compile(r"^(sku|oe|name)\s*[:：]\s*", re.IGNORECASE)


def _as_typed(raw: str | None) -> str:
    """The query exactly as typed (no full-width folding), minus any sku:/oe:/name: prefix."""
    return _TYPED_PREFIX.sub("", (raw or "").strip(), count=1).strip()


def _exact(typed: str, norm: str) -> list[Candidate]:
    """Exact when the stored text equals what was typed; otherwise matched after normalizing."""
    rows = PartNumber.objects.filter(number_norm=norm).select_related("part")
    return [
        _candidate(pn, "exact", 1.0) if pn.number == typed else _candidate(pn, "normalized", 0.95)
        for pn in rows
    ]


def _prefix(norm: str, limit: int) -> list[Candidate]:
    """Stored number contains the query, or the query contains a stored number."""
    cond = Q(query__contains=F("number_norm")) & Q(norm_len__gte=MIN_CONTAINED_LEN)
    if len(norm) >= MIN_CONTAINED_LEN:
        cond |= Q(number_norm__contains=norm)
    rows = (
        PartNumber.objects.annotate(
            query=Value(norm, output_field=CharField()), norm_len=Length("number_norm")
        )
        .filter(cond)
        .exclude(number_norm=norm)
        .select_related("part")
        .order_by("norm_len")[: limit * 3]
    )
    return [
        _candidate(pn, "prefix", 0.8 * min(len(norm), pn.norm_len) / max(len(norm), pn.norm_len))
        for pn in rows
    ]


def _fuzzy(norm: str, limit: int) -> list[Candidate]:
    if len(norm) < 3:
        return []
    if connection.vendor == "postgresql":
        return _fuzzy_trigram(norm, limit)
    return _fuzzy_python(norm, limit)


def _fuzzy_trigram(norm: str, limit: int) -> list[Candidate]:
    from django.contrib.postgres.search import TrigramSimilarity

    rows = (
        PartNumber.objects.filter(number_norm__trigram_similar=norm)  # uses the GIN index
        .annotate(similarity=TrigramSimilarity("number_norm", norm))
        .filter(similarity__gte=FUZZY_THRESHOLD)
        .exclude(number_norm=norm)
        .select_related("part")
        .order_by("-similarity")[: limit * 3]
    )
    return [_candidate(pn, "fuzzy", pn.similarity) for pn in rows]


def _fuzzy_python(norm: str, limit: int) -> list[Candidate]:
    """SQLite fallback: score numbers sharing the first or last three characters."""
    pool = (
        PartNumber.objects.filter(
            Q(number_norm__startswith=norm[:3]) | Q(number_norm__endswith=norm[-3:])
        )
        .exclude(number_norm=norm)
        .select_related("part")[:POOL_LIMIT]
    )
    scored = []
    for pn in pool:
        ratio = difflib.SequenceMatcher(None, norm, pn.number_norm).ratio()
        if ratio >= FALLBACK_THRESHOLD:
            scored.append(_candidate(pn, "fuzzy", ratio))
    return sorted(scored, key=lambda c: -c.score)[: limit * 3]


def _by_sku(text: str, limit: int) -> list[Candidate]:
    typed = text.strip()
    exact = Part.objects.filter(sku__iexact=typed).first()
    if exact:
        return [Candidate(exact, "exact", 1.0, exact.sku, "SKU")]
    return [
        Candidate(p, "prefix", 0.8, p.sku, "SKU")
        for p in Part.objects.filter(sku__istartswith=typed).order_by("sku")[:limit]
    ]


def _by_name(text: str, limit: int) -> list[Candidate]:
    """Every token must hit a name, category or fitment field; brand aliases are expanded."""
    tokens = [t for t in text.replace(",", " ").split() if t]
    if not tokens:
        return []
    qs = Part.objects.all()
    for token in tokens:
        brand = canonical_brand(token)
        cond = (
            Q(name_en__icontains=token)
            | Q(name_zh__icontains=token)
            | Q(category__name__icontains=token)
            | Q(category__name_en__icontains=token)
            | Q(fitments__model__icontains=token)
            | Q(fitments__make__icontains=brand or token)
        )
        qs = qs.filter(cond)
    parts = list(qs.distinct().order_by("-completeness_score", "sku")[:limit])
    if parts:
        return [Candidate(p, "name", 0.7) for p in parts]

    if connection.vendor == "postgresql":  # nothing matched literally: try misspellings
        from django.contrib.postgres.search import TrigramWordSimilarity

        rows = (
            Part.objects.annotate(similarity=TrigramWordSimilarity(text, "name_en"))
            .filter(similarity__gte=NAME_THRESHOLD)
            .order_by("-similarity", "sku")[:limit]
        )
        return [Candidate(p, "name", round(0.6 * p.similarity, 3)) for p in rows]
    return []


def _best_per_part(candidates: list[Candidate]) -> list[Candidate]:
    best: dict[int, Candidate] = {}
    for c in candidates:
        current = best.get(c.part.pk)
        if current is None or c.sort_key < current.sort_key:
            best[c.part.pk] = c
    return sorted(best.values(), key=lambda c: c.sort_key)
