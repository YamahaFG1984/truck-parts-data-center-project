"""Only apps/archive/services/review.py may change which product a record belongs to,
or group products (docs/archive-design.html §9, CLAUDE.md). This test reads the code."""

import re
from pathlib import Path

APPS = Path(__file__).resolve().parents[2]
ALLOWED = APPS / "archive" / "services" / "review.py"
WRITES = [
    re.compile(r"Membership\.objects\.(create|bulk_create|update|get_or_create|"
               r"update_or_create|bulk_update)"),
    re.compile(r"memberships\.(create|update|add|set)\("),
    re.compile(r"\.product(_id)?\s*=(?!=)"),
    re.compile(r"\.merged_into\s*=(?!=)"),
    re.compile(r"\.update\([^)]*\b(product|product_id|merged_into)="),
    re.compile(r"Product\.Status\.(GROUPED|MERGED|INDEPENDENT)"),
]


def test_nothing_outside_review_changes_membership_or_grouping():
    offenders = []
    for path in APPS.rglob("*.py"):
        if path == ALLOWED or "tests" in path.parts or "migrations" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in WRITES):
                offenders.append(f"{path.relative_to(APPS)}:{number}: {line.strip()}")
    assert offenders == []


def test_the_guard_would_catch_a_write():
    assert any(p.search("membership.product = other") for p in WRITES)
    assert any(p.search("Membership.objects.create(product=p)") for p in WRITES)
    assert any(p.search("qs.filter(x=1).update(product=other)") for p in WRITES)
    assert not any(p.search("if membership.product == other:") for p in WRITES)
    assert not any(p.search('merged_into = models.ForeignKey("self")') for p in WRITES)
