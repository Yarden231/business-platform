"""The audit action catalogue.

`activity_log.action` is plain `TEXT`, so the Python enum is the gate. These
tests make sure the gate stays a gate: consistent, unambiguous values that the
web application's Hebrew catalog can key off.
"""

from __future__ import annotations

import re

import pytest

from app.audit.actions import AuditAction, AuditEntityType

SCREAMING_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@pytest.mark.parametrize("member", list(AuditAction) + list(AuditEntityType))
def test_values_are_screaming_snake_case_and_match_their_name(member: AuditAction) -> None:
    assert SCREAMING_SNAKE.match(member.value)
    assert member.name == member.value


def test_values_are_unique() -> None:
    values = [action.value for action in AuditAction]

    assert len(values) == len(set(values))


def test_the_catalogue_covers_the_documented_actions() -> None:
    """docs/domain-model.md §7. A phase that adds an action updates both."""
    documented = {
        "USER_LOGGED_IN",
        "USER_LOGIN_FAILED",
        "USER_LOGGED_OUT",
        "USER_CREATED",
        "USER_UPDATED",
        "USER_DEACTIVATED",
        "USER_ACTIVATED",
        "USER_PASSWORD_CHANGED",
        "USER_PASSWORD_RESET",
        "CSRF_VALIDATION_FAILED",
        "PERSON_CREATED",
        "PERSON_UPDATED",
        "PERSON_ARCHIVED",
        "PERSON_UNARCHIVED",
        "CASE_CREATED",
        "CASE_UPDATED",
        "CASE_STATUS_CHANGED",
        "CASE_ASSIGNED",
        "CASE_UNASSIGNED",
        "CASE_PRIMARY_ASSIGNEE_CHANGED",
        "CASE_ARCHIVED",
        "CASE_UNARCHIVED",
        "PARTICIPANT_ADDED",
        "PARTICIPANT_REMOVED",
        "DOCUMENT_REQUIREMENT_CREATED",
        "DOCUMENT_REQUIREMENT_UPDATED",
        "DOCUMENT_REQUIREMENT_ARCHIVED",
        "DOCUMENT_SUBMITTED",
        "DOCUMENT_APPROVED",
        "DOCUMENT_REJECTED",
        "DOCUMENT_DOWNLOADED",
    }

    assert {action.value for action in AuditAction} == documented
