"""The paginated envelope every list endpoint returns (docs/api.md §3)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.pagination import Page


class PaginatedResponse[ItemT](BaseModel):
    """One page of `ItemT`, plus the total the client needs for page numbers."""

    items: list[ItemT]
    total: int = Field(description="Rows matching the filters, ignoring pagination.")
    page: int = Field(description="1-based page number.")
    page_size: int

    @classmethod
    def of(cls, page: Page[ItemT]) -> PaginatedResponse[ItemT]:
        """Wrap a service result. The items are already response models."""
        return cls(
            items=list(page.items),
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )
