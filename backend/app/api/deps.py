"""Router-facing dependency aliases (implementation lives in app.core.tenancy)."""

from app.core.tenancy import (
    AdminUser,
    ApiCompany,
    CurrentCompany,
    CurrentUser,
    DbSession,
    PublicCompany,
    ReadActor,
    SingleCompany,
    WriteActor,
    get_current_user,
    require_admin,
)

__all__ = [
    "AdminUser",
    "ApiCompany",
    "CurrentCompany",
    "CurrentUser",
    "DbSession",
    "PublicCompany",
    "ReadActor",
    "SingleCompany",
    "WriteActor",
    "get_current_user",
    "require_admin",
]
