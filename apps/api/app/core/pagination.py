"""Offset pagination (docs/api.md §3).

Offset rather than keyset, deliberately: the dashboard needs total counts and
page numbers, and the data volume of a single consultancy makes keyset
pagination premature (ADR-0016).

`PageRequest` is what a service receives and `Page` is what it returns, so the
bounds live here rather than being restated by every endpoint. The HTTP layer
turns a query string into the former and the latter into a Pydantic model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Published in `docs/api.md` and mirrored by the query-parameter constraints on
#: every list endpoint, so an out-of-range page size is a `422` rather than a
#: silently clamped value.
DEFAULT_PAGE_SIZE: Final = 25
MAX_PAGE_SIZE: Final = 100


@dataclass(frozen=True, slots=True)
class PageRequest:
    """A validated slice request. `page` is 1-based, as in the API contract."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be 1 or greater")
        if not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of results plus the total the caller needs to render pagination."""

    items: tuple[T, ...]
    total: int
    page: int
    page_size: int
