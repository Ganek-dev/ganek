"""Router-facing dependency aliases (implementation lives in app.core.tenancy)."""

from app.core.tenancy import (
    AdminUser,
    CurrentCompany,
    CurrentUser,
    DbSession,
    PublicCompany,
    SingleCompany,
    get_current_user,
    require_admin,
)

__all__ = [
    "AdminUser",
    "CurrentCompany",
    "CurrentUser",
    "DbSession",
    "PublicCompany",
    "SingleCompany",
    "get_current_user",
    "require_admin",
]
