"""Every search box query becomes an Inquiry (PRD F7), in exactly one INSERT.

Typing produces several requests ("2044", "20443", "20443906"); they are all
written and the half-typed ones are hidden when read (Inquiry.objects.settled()),
so the search itself never pays for an extra lookup.
"""

import re
import unicodedata

from apps.catalog.services.normalize import split_query_prefix

from ..models import Inquiry

MAX_CANDIDATES = 10
_SEPARATORS = re.compile(r"[\s\-_./:：,，]+")


def query_key(raw: str) -> str:
    """One key rule for every query, so typing "2149" -> "2149-" -> "2149-5672" forms
    a prefix chain and spellings group together: full-width folded, lower-cased,
    spaces and separators removed, Chinese kept.
    "2044-3906" -> "20443906", "Brake  PAD volvo" -> "brakepadvolvo", "刹车片" -> "刹车片"."""
    _, text = split_query_prefix(raw)
    return _SEPARATORS.sub("", unicodedata.normalize("NFKC", text).casefold())[:200]


def log_text_search(raw: str, candidates: list, user) -> Inquiry:
    """One INSERT. The best candidate is recorded as the automatic match; the person
    can pick another one on the inquiry page."""
    top = candidates[0] if candidates else None
    return Inquiry.objects.create(
        input_type=Inquiry.InputType.TEXT,
        raw_input=raw,
        query_key=query_key(raw),
        matched_part=top.part if top else None,
        finding={
            "auto": True,
            "hits": len(candidates),
            "candidates": [
                {"part_id": c.part.pk, "match_type": c.match_type, "score": c.score,
                 "matched_number": c.matched_number, "matched_kind": c.matched_kind}
                for c in candidates[:MAX_CANDIDATES]
            ],
        },
        created_by=user if user.is_authenticated else None,
    )
