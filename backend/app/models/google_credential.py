import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserGoogleCredential(TimestampMixin, Base):
    """One connected Google Calendar per user.

    The refresh token is Fernet-encrypted (app/core/crypto.py) and must
    never be logged or serialized. Access tokens are never persisted.
    """

    __tablename__ = "user_google_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    refresh_token_encrypted: Mapped[str] = mapped_column(String(1000))
    google_email: Mapped[str] = mapped_column(String(320))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # set when a refresh grant fails (revoked/expired consent) — drives the
    # Account card's "reconnect" state instead of silent breakage
    last_refresh_error: Mapped[str | None] = mapped_column(String(200))
