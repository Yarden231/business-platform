"""Internal user administration and the staff directory (docs/api.md §5).

Admin-only apart from the directory, which any authenticated staff member needs
in order to see who a case is assigned to. The role gate is a dependency here
*and* re-checked in `app.services.users`, so neither layer is the only thing
standing between an employee and user management.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Query, status

from app.api.dependencies import (
    AdminActor,
    AppSettings,
    DbSession,
    RequestOriginDep,
    StaffActor,
)
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageRequest
from app.domain.enums import UserRole
from app.schemas.errors import ErrorEnvelope
from app.schemas.pagination import PaginatedResponse
from app.schemas.users import (
    DirectoryEntryResponse,
    ProvisionedUserResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.users import UserService

router = APIRouter(prefix="/users", tags=["users"])

_Responses = dict[int | str, dict[str, Any]]

_ADMIN_ONLY: Final[_Responses] = {
    401: {"model": ErrorEnvelope, "description": "No usable session."},
    403: {
        "model": ErrorEnvelope,
        "description": "FORBIDDEN, CSRF_TOKEN_INVALID or PASSWORD_CHANGE_REQUIRED.",
    },
}
_USER_NOT_FOUND: Final[_Responses] = {
    404: {"model": ErrorEnvelope, "description": "USER_NOT_FOUND."}
}
_UNAUTHENTICATED: Final[_Responses] = {
    401: {"model": ErrorEnvelope, "description": "No usable session."}
}


# Registered before `/{user_id}` on purpose. FastAPI matches routes in
# declaration order, so with the parameterised route first, `/users/directory`
# would be parsed as a `user_id` and rejected as a malformed UUID.
@router.get("/directory", summary="Staff directory", responses=_UNAUTHENTICATED)
async def list_directory(
    actor: StaffActor,
    session: DbSession,
    settings: AppSettings,
) -> list[DirectoryEntryResponse]:
    """Active staff accounts as `{id, full_name, role}`, for assignee pickers.

    Unpaginated: this is the internal staff list of a single consultancy, it is
    read to populate a dropdown, and paging it would make every caller
    reassemble it. Deactivated accounts are omitted — they cannot be given new
    work — while historical audit and assignment rows still resolve to them.
    """
    entries = await UserService(session, settings).list_directory(actor)
    return [DirectoryEntryResponse.of(entry) for entry in entries]


@router.get("", summary="List users", responses=_ADMIN_ONLY)
async def list_users(
    actor: AdminActor,
    session: DbSession,
    settings: AppSettings,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    query: Annotated[str | None, Query(max_length=200)] = None,
    role: Annotated[UserRole | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> PaginatedResponse[UserResponse]:
    """Paginated staff accounts, filterable by free text, role and activation state."""
    result = await UserService(session, settings).list_users(
        actor,
        page=PageRequest(page=page, page_size=page_size),
        query=query,
        role=role,
        is_active=is_active,
    )
    return PaginatedResponse[UserResponse](
        items=[UserResponse.of(view) for view in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff account",
    responses={
        **_ADMIN_ONLY,
        409: {"model": ErrorEnvelope, "description": "USER_EMAIL_CONFLICT."},
    },
)
async def create_user(
    body: UserCreateRequest,
    actor: AdminActor,
    session: DbSession,
    settings: AppSettings,
    origin: RequestOriginDep,
) -> ProvisionedUserResponse:
    """Create an account and return its one-time temporary password (ADR-0026).

    The password in this response is the only copy that will ever exist in
    plaintext. It is not stored, not logged, not audited and not retrievable
    from any other endpoint; if it is lost, the fix is
    `POST /users/{user_id}/password-reset`.
    """
    provisioned = await UserService(session, settings).create_user(
        actor,
        email=str(body.email),
        full_name=body.full_name,
        role=body.role,
        origin=origin,
    )
    return ProvisionedUserResponse(
        user=UserResponse.of(provisioned.user),
        temporary_password=provisioned.temporary_password,
    )


@router.get(
    "/{user_id}",
    summary="Read a staff account",
    responses={**_ADMIN_ONLY, **_USER_NOT_FOUND},
)
async def get_user(
    user_id: uuid.UUID,
    actor: AdminActor,
    session: DbSession,
    settings: AppSettings,
) -> UserResponse:
    return UserResponse.of(await UserService(session, settings).get_user(actor, user_id))


@router.patch(
    "/{user_id}",
    summary="Update a staff account",
    responses={
        **_ADMIN_ONLY,
        **_USER_NOT_FOUND,
        409: {
            "model": ErrorEnvelope,
            "description": "USER_SELF_DEACTIVATION or USER_LAST_ADMIN.",
        },
    },
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    actor: AdminActor,
    session: DbSession,
    settings: AppSettings,
    origin: RequestOriginDep,
) -> UserResponse:
    """Change the name, the role or the activation state. Nothing else is settable.

    Deactivating revokes every session of the target in the same transaction,
    so their next request fails rather than waiting for a cookie to expire.
    """
    view = await UserService(session, settings).update_user(
        actor,
        user_id,
        full_name=body.full_name,
        role=body.role,
        deactivated=body.deactivated,
        origin=origin,
    )
    return UserResponse.of(view)


@router.post(
    "/{user_id}/password-reset",
    summary="Issue a new temporary password",
    responses={**_ADMIN_ONLY, **_USER_NOT_FOUND},
)
async def reset_password(
    user_id: uuid.UUID,
    actor: AdminActor,
    session: DbSession,
    settings: AppSettings,
    origin: RequestOriginDep,
) -> ProvisionedUserResponse:
    """Replace a user's password with a fresh temporary one (ADR-0026).

    This is the whole account-recovery story in Release 1: there is no email
    service, so an admin does this and passes the password on out of band. It
    clears any lockout, forces rotation at next login, and revokes every
    session the user has — including the one they may be using right now.
    """
    provisioned = await UserService(session, settings).reset_password(actor, user_id, origin=origin)
    return ProvisionedUserResponse(
        user=UserResponse.of(provisioned.user),
        temporary_password=provisioned.temporary_password,
    )
