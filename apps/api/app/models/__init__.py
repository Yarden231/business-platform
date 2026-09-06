"""SQLAlchemy ORM mappings.

Importing this package registers every table on `Base.metadata`, which is what
Alembic's autogenerate compares the database against. A model that is not
re-exported here is invisible to migrations, so new tables belong in this list.

Phase 1 maps the infrastructure tables only. `people`, `cases` and the document
tables arrive with the phases that use them.
"""

from app.db.base import Base
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.models.user_session import UserSession

__all__ = [
    "ActivityLog",
    "Base",
    "User",
    "UserIdentity",
    "UserSession",
]
