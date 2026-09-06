"""FastAPI dependencies shared by routers.

This is the only module in the HTTP layer that names a persistence type, and it
does so to wire the request-scoped session — not to query anything. Routers
receive `DbSession` and hand it to a service.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
