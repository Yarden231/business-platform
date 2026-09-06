"""Person identifiers: normalisation, Israeli ID checksum, masking.

Pure functions. The checksum lives here so it can be unit-tested without a
database or an HTTP client (docs/architecture.md §4). Validation of the
identifier *pair* — both present or both absent — is also here, because the
service and the request models must agree on one rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.domain.enums import PersonIdType

#: Israeli IDs are nine digits including the check digit.
ISRAELI_ID_LENGTH: Final = 9

#: Passports and foreign identifiers have no shared format; this is a storage
#: bound, not a format rule.
IDENTIFIER_MAX_LENGTH: Final = 64

#: How many trailing characters of an identifier remain visible when masked.
MASK_VISIBLE_CHARS: Final = 3


@dataclass(frozen=True, slots=True)
class IdentifierPair:
    """A validated `(id_type, id_number)` or the honest absence of both."""

    id_type: PersonIdType | None
    id_number: str | None

    @property
    def is_present(self) -> bool:
        return self.id_type is not None and self.id_number is not None


@dataclass(frozen=True, slots=True)
class IdentifierIssue:
    """One reason an identifier was refused. `field` is `id_type` or `id_number`."""

    field: str
    issue: str


def digits_only(value: str) -> str:
    """Keep decimal digits; drop spaces, dashes and everything else."""
    return "".join(character for character in value if character.isdigit())


def israeli_id_checksum_valid(digits: str) -> bool:
    """The Luhn-like check used by Israeli identity cards.

    Positions are 0-indexed from the left. Even positions are taken as-is;
    odd positions are doubled and, if the product is greater than 9, have 9
    subtracted. The number is valid when the sum is divisible by 10.
    """
    if len(digits) != ISRAELI_ID_LENGTH or not digits.isdigit():
        return False
    total = 0
    for index, character in enumerate(digits):
        step = int(character) * (1 if index % 2 == 0 else 2)
        if step > 9:
            step -= 9
        total += step
    return total % 10 == 0


def normalize_identifier(id_type: PersonIdType, raw: str) -> str:
    """The stored form of an identifier.

    Israeli IDs become nine digits (leading zeros preserved). Passports and
    foreign identifiers are trimmed; they have no further normalisation
    because the issuing authority's own spacing and case are part of the
    number as presented.
    """
    if id_type is PersonIdType.ISRAELI_ID:
        return digits_only(raw)
    return raw.strip()


def validate_identifier(id_type: PersonIdType, raw: str) -> list[IdentifierIssue]:
    """Every reason `raw` is not a usable identifier of `id_type`.

    Returns an empty list when the value is acceptable. The caller decides
    whether that is a `422` or a domain rejection.
    """
    if id_type is PersonIdType.ISRAELI_ID:
        digits = digits_only(raw)
        if len(digits) != ISRAELI_ID_LENGTH:
            return [IdentifierIssue(field="id_number", issue="israeli_id_length")]
        if not israeli_id_checksum_valid(digits):
            return [IdentifierIssue(field="id_number", issue="israeli_id_checksum")]
        return []

    stripped = raw.strip()
    if not stripped:
        return [IdentifierIssue(field="id_number", issue="blank")]
    if len(stripped) > IDENTIFIER_MAX_LENGTH:
        return [IdentifierIssue(field="id_number", issue="too_long")]
    return []


def parse_identifier_pair(
    id_type: PersonIdType | None,
    id_number: str | None,
) -> tuple[IdentifierPair | None, list[IdentifierIssue]]:
    """Both present (and valid) or both absent. Anything else is an issue list.

    Empty / whitespace-only `id_number` is treated as absent, so a form that
    sends `id_type` without a number cannot sneak past as a typed blank.
    """
    type_present = id_type is not None
    number_text = id_number.strip() if id_number is not None else ""
    number_present = bool(number_text)

    if not type_present and not number_present:
        return IdentifierPair(id_type=None, id_number=None), []
    if type_present and not number_present:
        return None, [IdentifierIssue(field="id_number", issue="required_with_id_type")]
    if number_present and not type_present:
        return None, [IdentifierIssue(field="id_type", issue="required_with_id_number")]

    assert id_type is not None  # noqa: S101 - guarded above
    issues = validate_identifier(id_type, number_text)
    if issues:
        return None, issues
    return IdentifierPair(id_type=id_type, id_number=normalize_identifier(id_type, number_text)), []


def mask_identifier(id_number: str | None) -> str | None:
    """A directory-safe rendering of an identifier (ADR-0027).

    All but the last three characters become `*`. A missing identifier stays
    missing — there is nothing to mask. Short values (three characters or
    fewer) are fully masked so a two-digit remnant cannot become the number.
    """
    if id_number is None:
        return None
    if len(id_number) <= MASK_VISIBLE_CHARS:
        return "*" * len(id_number)
    return ("*" * (len(id_number) - MASK_VISIBLE_CHARS)) + id_number[-MASK_VISIBLE_CHARS:]
