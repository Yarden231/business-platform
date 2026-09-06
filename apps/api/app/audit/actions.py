"""The audit action catalogue.

Every value here is one the specification and `docs/domain-model.md` §7 already
name; nothing is invented. Most of them cannot be raised yet — the entities they
describe arrive in Phases 2 and 4-6 — but the catalogue is written once so that
`domain/activity.py` can classify actions against a complete list in Phase 5,
and so that adding an action later is a change to this file rather than a
decision about naming.

The column is plain `TEXT`: values are written only through `AuditRecorder`,
which takes an `AuditAction`, so the type system is the gate.
"""

from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    """What happened. The past tense is deliberate — an audit row is a fact."""

    # Identity and access (Phase 2)
    USER_LOGGED_IN = "USER_LOGGED_IN"
    USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
    USER_LOGGED_OUT = "USER_LOGGED_OUT"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    USER_PASSWORD_CHANGED = "USER_PASSWORD_CHANGED"  # noqa: S105 - an event name, not a secret

    # People (Phase 4)
    PERSON_CREATED = "PERSON_CREATED"
    PERSON_UPDATED = "PERSON_UPDATED"
    PERSON_ARCHIVED = "PERSON_ARCHIVED"
    PERSON_UNARCHIVED = "PERSON_UNARCHIVED"

    # Cases, participants and assignments (Phase 5)
    CASE_CREATED = "CASE_CREATED"
    CASE_UPDATED = "CASE_UPDATED"
    CASE_STATUS_CHANGED = "CASE_STATUS_CHANGED"
    CASE_ASSIGNED = "CASE_ASSIGNED"
    CASE_UNASSIGNED = "CASE_UNASSIGNED"
    CASE_PRIMARY_ASSIGNEE_CHANGED = "CASE_PRIMARY_ASSIGNEE_CHANGED"
    CASE_ARCHIVED = "CASE_ARCHIVED"
    CASE_UNARCHIVED = "CASE_UNARCHIVED"
    PARTICIPANT_ADDED = "PARTICIPANT_ADDED"
    PARTICIPANT_REMOVED = "PARTICIPANT_REMOVED"

    # Documents (Phase 6)
    DOCUMENT_REQUIREMENT_CREATED = "DOCUMENT_REQUIREMENT_CREATED"
    DOCUMENT_REQUIREMENT_UPDATED = "DOCUMENT_REQUIREMENT_UPDATED"
    DOCUMENT_REQUIREMENT_ARCHIVED = "DOCUMENT_REQUIREMENT_ARCHIVED"
    DOCUMENT_SUBMITTED = "DOCUMENT_SUBMITTED"
    DOCUMENT_APPROVED = "DOCUMENT_APPROVED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED"


class AuditEntityType(StrEnum):
    """What the action happened to.

    `entity_id` is interpreted against this, which is how the audit screen
    resolves a row back to the thing it describes.
    """

    USER = "USER"
    USER_IDENTITY = "USER_IDENTITY"
    SESSION = "SESSION"
    PERSON = "PERSON"
    CASE = "CASE"
    CASE_PARTICIPANT = "CASE_PARTICIPANT"
    CASE_ASSIGNMENT = "CASE_ASSIGNMENT"
    DOCUMENT_REQUIREMENT = "DOCUMENT_REQUIREMENT"
    DOCUMENT_SUBMISSION = "DOCUMENT_SUBMISSION"
