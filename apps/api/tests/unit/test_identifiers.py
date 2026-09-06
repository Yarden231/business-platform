"""Israeli ID checksum, identifier pairing and masking (Q7 / ADR-0040)."""

from __future__ import annotations

import pytest

from app.domain.enums import PersonIdType
from app.domain.identifiers import (
    israeli_id_checksum_valid,
    mask_identifier,
    normalize_identifier,
    parse_identifier_pair,
    validate_identifier,
)
from tests.support.factories import VALID_ISRAELI_ID, VALID_ISRAELI_ID_OTHER


class TestIsraeliIdChecksum:
    def test_a_known_valid_number_passes(self) -> None:
        assert israeli_id_checksum_valid(VALID_ISRAELI_ID) is True

    def test_another_known_valid_number_passes(self) -> None:
        assert israeli_id_checksum_valid(VALID_ISRAELI_ID_OTHER) is True

    def test_a_wrong_check_digit_fails(self) -> None:
        assert israeli_id_checksum_valid("123456780") is False

    def test_a_short_number_fails(self) -> None:
        assert israeli_id_checksum_valid("12345678") is False

    def test_a_long_number_fails(self) -> None:
        assert israeli_id_checksum_valid("1234567820") is False

    def test_non_digits_fail(self) -> None:
        assert israeli_id_checksum_valid("12345678a") is False

    def test_leading_zeros_are_significant(self) -> None:
        """An Israeli ID is nine digits; leading zeros are part of the number."""
        assert israeli_id_checksum_valid("000000018") is True
        assert israeli_id_checksum_valid("18") is False


class TestValidateIdentifier:
    def test_israeli_id_accepts_spaces_and_dashes(self) -> None:
        assert validate_identifier(PersonIdType.ISRAELI_ID, "123-456-782") == []
        assert validate_identifier(PersonIdType.ISRAELI_ID, "123 456 782") == []

    def test_israeli_id_rejects_a_bad_checksum(self) -> None:
        issues = validate_identifier(PersonIdType.ISRAELI_ID, "123456780")
        assert [issue.issue for issue in issues] == ["israeli_id_checksum"]

    def test_passport_rejects_a_blank(self) -> None:
        issues = validate_identifier(PersonIdType.PASSPORT, "   ")
        assert [issue.issue for issue in issues] == ["blank"]

    def test_foreign_id_accepts_an_opaque_string(self) -> None:
        assert validate_identifier(PersonIdType.FOREIGN_ID, "AB-99/4") == []


class TestParseIdentifierPair:
    def test_both_absent_is_allowed(self) -> None:
        pair, issues = parse_identifier_pair(None, None)
        assert issues == []
        assert pair is not None
        assert pair.is_present is False

    def test_whitespace_only_number_without_a_type_is_absent(self) -> None:
        pair, issues = parse_identifier_pair(None, "   ")
        assert issues == []
        assert pair is not None
        assert pair.is_present is False

    def test_a_type_without_a_number_is_refused(self) -> None:
        pair, issues = parse_identifier_pair(PersonIdType.PASSPORT, None)
        assert pair is None
        assert [issue.issue for issue in issues] == ["required_with_id_type"]

    def test_a_number_without_a_type_is_refused(self) -> None:
        pair, issues = parse_identifier_pair(None, "AB1234567")
        assert pair is None
        assert [issue.issue for issue in issues] == ["required_with_id_number"]
        assert issues[0].field == "id_type"

    def test_a_valid_israeli_id_is_normalised_to_digits(self) -> None:
        pair, issues = parse_identifier_pair(PersonIdType.ISRAELI_ID, "123-456-782")
        assert issues == []
        assert pair is not None
        assert pair.id_type is PersonIdType.ISRAELI_ID
        assert pair.id_number == VALID_ISRAELI_ID


class TestNormalizeIdentifier:
    def test_israeli_id_keeps_digits_only(self) -> None:
        assert normalize_identifier(PersonIdType.ISRAELI_ID, " 123-456-782 ") == VALID_ISRAELI_ID

    def test_passport_is_trimmed_but_not_rewritten(self) -> None:
        assert normalize_identifier(PersonIdType.PASSPORT, "  AB1234567  ") == "AB1234567"


class TestMaskIdentifier:
    def test_a_missing_identifier_stays_missing(self) -> None:
        assert mask_identifier(None) is None

    def test_an_israeli_id_keeps_the_last_three_digits(self) -> None:
        assert mask_identifier(VALID_ISRAELI_ID) == "******782"

    def test_a_short_value_is_fully_masked(self) -> None:
        assert mask_identifier("12") == "**"

    @pytest.mark.parametrize("value", ["a", "ab", "abc"])
    def test_three_or_fewer_characters_do_not_leak(self, value: str) -> None:
        masked = mask_identifier(value)
        assert masked is not None
        assert set(masked) == {"*"}

    def test_four_characters_keep_only_the_last_three(self) -> None:
        assert mask_identifier("abcd") == "*bcd"
