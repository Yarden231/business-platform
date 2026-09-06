"""The people directory (docs/api.md §5, ADR-0027).

Open to any authenticated staff member. Representation and write rights are
decided by `PersonAccessService.has_full_access`, not by hiding a button.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession, RequestOriginDep, StaffActor
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageRequest
from app.schemas.errors import ErrorEnvelope
from app.schemas.pagination import PaginatedResponse
from app.schemas.people import (
    PersonCaseItem,
    PersonCreateRequest,
    PersonDetailResponse,
    PersonReadResponse,
    PersonSummaryResponse,
    PersonUpdateRequest,
)
from app.services.people import PeopleService, PersonDetailView, PersonSummaryView

router = APIRouter(prefix="/people", tags=["people"])

_Responses = dict[int | str, dict[str, Any]]

_AUTHENTICATED: Final[_Responses] = {
    401: {"model": ErrorEnvelope, "description": "No usable session."},
    403: {
        "model": ErrorEnvelope,
        "description": "CSRF_TOKEN_INVALID or PASSWORD_CHANGE_REQUIRED.",
    },
}
_PERSON_NOT_FOUND: Final[_Responses] = {
    404: {"model": ErrorEnvelope, "description": "PERSON_NOT_FOUND."}
}


def _read_response(view: PersonSummaryView | PersonDetailView) -> PersonReadResponse:
    if isinstance(view, PersonDetailView):
        return PersonDetailResponse.of(view)
    return PersonSummaryResponse.of(view)


@router.get("", summary="List people", responses=_AUTHENTICATED)
async def list_people(
    actor: StaffActor,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    query: Annotated[str | None, Query(max_length=200)] = None,
    archived: Annotated[bool | None, Query()] = None,
) -> PaginatedResponse[PersonReadResponse]:
    """Paginated directory search.

    Admins receive `PersonDetail`. Employees receive `PersonSummary` (masked
    identifier, no contact fields) until a person participates in a case
    assigned to them — which cannot happen until Phase 5.
    """
    result = await PeopleService(session).list_people(
        actor,
        page=PageRequest(page=page, page_size=page_size),
        query=query,
        archived=archived,
    )
    return PaginatedResponse[PersonReadResponse](
        items=[_read_response(view) for view in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a person",
    responses={
        **_AUTHENTICATED,
        409: {"model": ErrorEnvelope, "description": "PERSON_IDENTIFIER_CONFLICT."},
        422: {"model": ErrorEnvelope, "description": "VALIDATION_ERROR."},
    },
)
async def create_person(
    body: PersonCreateRequest,
    actor: StaffActor,
    session: DbSession,
    origin: RequestOriginDep,
) -> PersonDetailResponse:
    """Create a person. The response is always detail — the caller authored it."""
    view = await PeopleService(session).create_person(
        actor,
        first_name=body.first_name,
        last_name=body.last_name,
        id_type=body.id_type,
        id_number=body.id_number,
        email=body.email,
        phone=body.phone,
        address=body.address,
        workplace=body.workplace,
        organization_name=body.organization_name,
        license_number=body.license_number,
        notes=body.notes,
        origin=origin,
    )
    return PersonDetailResponse.of(view)


@router.get(
    "/{person_id}",
    summary="Read a person",
    responses={**_AUTHENTICATED, **_PERSON_NOT_FOUND},
)
async def get_person(
    person_id: uuid.UUID,
    actor: StaffActor,
    session: DbSession,
) -> PersonReadResponse:
    """Detail when the access predicate holds; summary otherwise. Never 403."""
    return _read_response(await PeopleService(session).get_person(actor, person_id))


@router.patch(
    "/{person_id}",
    summary="Update a person",
    responses={
        **_AUTHENTICATED,
        **_PERSON_NOT_FOUND,
        403: {
            "model": ErrorEnvelope,
            "description": "PERSON_ACCESS_DENIED, CSRF_TOKEN_INVALID or PASSWORD_CHANGE_REQUIRED.",
        },
        409: {"model": ErrorEnvelope, "description": "PERSON_IDENTIFIER_CONFLICT."},
    },
)
async def update_person(
    person_id: uuid.UUID,
    body: PersonUpdateRequest,
    actor: StaffActor,
    session: DbSession,
    origin: RequestOriginDep,
) -> PersonDetailResponse:
    """Edit a person. Employees need an assigned-case participation (Phase 5)."""
    view = await PeopleService(session).update_person(
        actor,
        person_id,
        fields=body.model_dump(exclude_unset=True),
        origin=origin,
    )
    return PersonDetailResponse.of(view)


@router.post(
    "/{person_id}/archive",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive a person",
    responses={
        **_AUTHENTICATED,
        **_PERSON_NOT_FOUND,
        403: {"model": ErrorEnvelope, "description": "FORBIDDEN — ADMIN only."},
        409: {"model": ErrorEnvelope, "description": "PERSON_ALREADY_ARCHIVED."},
    },
)
async def archive_person(
    person_id: uuid.UUID,
    actor: StaffActor,
    session: DbSession,
    origin: RequestOriginDep,
) -> Response:
    await PeopleService(session).archive_person(actor, person_id, origin=origin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{person_id}/unarchive",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unarchive a person",
    responses={
        **_AUTHENTICATED,
        **_PERSON_NOT_FOUND,
        403: {"model": ErrorEnvelope, "description": "FORBIDDEN — ADMIN only."},
        409: {"model": ErrorEnvelope, "description": "PERSON_NOT_ARCHIVED."},
    },
)
async def unarchive_person(
    person_id: uuid.UUID,
    actor: StaffActor,
    session: DbSession,
    origin: RequestOriginDep,
) -> Response:
    await PeopleService(session).unarchive_person(actor, person_id, origin=origin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{person_id}/cases",
    summary="List a person's cases",
    responses={**_AUTHENTICATED, **_PERSON_NOT_FOUND},
)
async def list_person_cases(
    person_id: uuid.UUID,
    actor: StaffActor,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PaginatedResponse[PersonCaseItem]:
    """Cases this person participates in, within the caller's scope.

    Always empty in Phase 4: `cases` does not exist. The person must still
    exist, so a typo is a 404 rather than a silent empty page.
    """
    result = await PeopleService(session).list_person_cases(
        actor,
        person_id,
        page=PageRequest(page=page, page_size=page_size),
    )
    return PaginatedResponse[PersonCaseItem](
        items=[],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
