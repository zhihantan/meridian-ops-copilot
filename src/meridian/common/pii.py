"""Free-text PII patterns for in-pipeline redaction (T04, BUILD).

Column-level Data Classification does not cover free text, so `notes` is redacted with these regexes.
They are valid in both Python `re` and Java regex, so tests score recall locally with the same
patterns the pipeline runs through `regexp_replace`.
"""

from __future__ import annotations

import re

# Order matters: card numbers before phones, so a 16-digit run is not half-matched as a phone.
PATTERNS: dict[str, str] = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "card": r"\b(?:\d[ -]?){12,18}\d\b",
    "national_id": r"\b[STFGM]\d{7}[A-Z]\b",
    "phone": r"(?:\+65[ -]?)?\b[689]\d{3}[ -]?\d{4}\b",
}
TOKENS = {"email": "[EMAIL]", "card": "[CARD]", "national_id": "[NRIC]", "phone": "[PHONE]"}

# Contract PII category -> the Data Classification system tag for it. ABAC policies match these
# tags, so a column the classifier tags is protected with no per-table change.
CLASS_TAGS = {
    "email": "class.email_address", "phone": "class.phone_number", "national_id": "class.sg_nric",
    "card": "class.credit_card", "dob": "class.date_of_birth", "name": "class.name", "address": "class.street_address",
}
# Tags that some ABAC policy masks or restricts (name and address stay visible to support by design).
COVERED_TAGS = {"class.email_address", "class.phone_number", "class.sg_nric", "class.sg_fin",
                "class.credit_card", "class.date_of_birth"}


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    for kind, pattern in PATTERNS.items():
        text = re.sub(pattern, TOKENS[kind], text)
    return text


def find_all(text: str | None) -> list[tuple[str, str]]:
    """(kind, value) for every PII match, using the same precedence as redact()."""
    found, remaining = [], text or ""
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, remaining):
            found.append((kind, match.group(0)))
        remaining = re.sub(pattern, TOKENS[kind], remaining)
    return found
