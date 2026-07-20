"""Router-facing dependency aliases (implementation lives in app.core.tenancy)."""

from app.core.tenancy import (
    CurrentCompany,
    CurrentUser,
    DbSession,
    PublicCompany,
    SingleCompany,
    get_current_user,
)

__all__ = [
    "CurrentCompany",
    "CurrentUser",
    "DbSession",
    "PublicCompany",
    "SingleCompany",
    "get_current_user",
]
