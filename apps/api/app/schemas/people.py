"""Request and response models for `/api/v1/people` (docs/api.md §5, ADR-0027)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import PersonIdType
from app.schemas.base import RequestModel
from app.services.people import PersonDetailView, PersonSummaryView

_NAME_MAX = 200
_IDENTIFIER_MAX = 64
_EMAIL_MAX = 320
_PHONE_MAX = 64
_ORG_MAX = 200
_LICENSE_MAX = 64
_NOTES_MAX = 8000
_ADDRESS_MAX = 2000


class PersonSummaryResponse(BaseModel):
    """Masked directory row. The fields an employee may see outside their cases."""

    representation: Literal["SUMMARY"] = "SUMMARY"
    id: uuid.UUID
    first_name: str
    last_name: str
    organization_name: str | None
    id_number_masked: str | None = Field(
        description="Identifier with all but the last three characters replaced by *."
    )
    archived_at: datetime | None

    @classmethod
    def of(cls, view: PersonSummaryView) -> PersonSummaryResponse:
        return cls(
            id=view.id,
            first_name=view.first_name,
            last_name=view.last_name,
            organization_name=view.organization_name,
            id_number_masked=view.id_number_masked,
            archived_at=view.archived_at,
        )


class PersonDetailResponse(BaseModel):
    """Full operational record. Never serialised without the access predicate.

    Create is the documented exception: the caller already authored these values.
    """

    representation: Literal["DETAIL"] = "DETAIL"
    id: uuid.UUID
    first_name: str
    last_name: str
    id_type: PersonIdType | None
    id_number: str | None
    email: str | None
    phone: str | None
    address: str | None
    workplace: str | None
    organization_name: str | None
    license_number: str | None
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    @classmethod
    def of(cls, view: PersonDetailView) -> PersonDetailResponse:
        return cls(
            id=view.id,
            first_name=view.first_name,
            last_name=view.last_name,
            id_type=view.id_type,
            id_number=view.id_number,
            email=view.email,
            phone=view.phone,
            address=view.address,
            workplace=view.workplace,
            organization_name=view.organization_name,
            license_number=view.license_number,
            notes=view.notes,
            created_by=view.created_by,
            created_at=view.created_at,
            updated_at=view.updated_at,
            archived_at=view.archived_at,
        )


#: Named so OpenAPI publishes `PaginatedResponse_PersonReadResponse_` rather
#: than the stringified `Annotated[Union[...]]` (ADR-0017).
type PersonReadResponse = Annotated[
    PersonSummaryResponse | PersonDetailResponse,
    Field(discriminator="representation"),
]


class PersonCreateRequest(RequestModel):
    """Body for `POST /api/v1/people`.

    `id_type` and `id_number` are both required together, or both omitted.
    Israeli IDs are validated (format + check digit) when the type is
    `ISRAELI_ID` (Q7 / ADR-0040).
    """

    first_name: str = Field(min_length=1, max_length=_NAME_MAX)
    last_name: str = Field(min_length=1, max_length=_NAME_MAX)
    id_type: PersonIdType | None = None
    id_number: str | None = Field(default=None, max_length=_IDENTIFIER_MAX)
    email: str | None = Field(default=None, max_length=_EMAIL_MAX)
    phone: str | None = Field(default=None, max_length=_PHONE_MAX)
    address: str | None = Field(default=None, max_length=_ADDRESS_MAX)
    workplace: str | None = Field(default=None, max_length=_ORG_MAX)
    organization_name: str | None = Field(default=None, max_length=_ORG_MAX)
    license_number: str | None = Field(default=None, max_length=_LICENSE_MAX)
    notes: str | None = Field(default=None, max_length=_NOTES_MAX)

    @model_validator(mode="after")
    def identifier_fields_travel_together(self) -> Self:
        type_given = self.id_type is not None
        number_given = self.id_number is not None and bool(self.id_number.strip())
        if type_given != number_given:
            raise ValueError("id_type and id_number must both be present or both be absent")
        return self


class PersonUpdateRequest(RequestModel):
    """Body for `PATCH /api/v1/people/{person_id}`.

    An explicit allowlist. Omitted fields are left alone. Sending `id_type`
    requires `id_number` (and vice versa); both null clears the identifier.
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    last_name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    id_type: PersonIdType | None = None
    id_number: str | None = Field(default=None, max_length=_IDENTIFIER_MAX)
    email: str | None = Field(default=None, max_length=_EMAIL_MAX)
    phone: str | None = Field(default=None, max_length=_PHONE_MAX)
    address: str | None = Field(default=None, max_length=_ADDRESS_MAX)
    workplace: str | None = Field(default=None, max_length=_ORG_MAX)
    organization_name: str | None = Field(default=None, max_length=_ORG_MAX)
    license_number: str | None = Field(default=None, max_length=_LICENSE_MAX)
    notes: str | None = Field(default=None, max_length=_NOTES_MAX)


class PersonCaseItem(BaseModel):
    """A case this person participates in.

    Cases do not exist yet. This endpoint always returns an empty page in
    Phase 4; the item schema arrives with Phase 5.
    """
