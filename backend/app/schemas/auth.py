import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import UserRole


class RegisterRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    altcha: str | None = Field(default=None, max_length=2000)  # core/challenge.py


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=128)


class GoogleSignupRequest(BaseModel):
    # the signed sub+email token arrives via the httponly signup cookie,
    # never the request body (GDPR G4)
    company_name: str = Field(min_length=1, max_length=200)


class GoogleSignupPending(BaseModel):
    email: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    email: EmailStr
    role: UserRole
    has_password: bool
    display_name: str | None = None
    display_label: str = ""
    # true only in the register response of a multi-mode signup awaiting
    # email verification (M5.7 H4); never set from ORM attributes
    pending_verification: bool = False
    # card A6: whether a second factor is on, and how many recovery codes
    # are unused (the account page nudges below three)
    mfa_enabled: bool = False
    recovery_codes_left: int = 0
    # login response only: the password passed, a code is needed next;
    # mfa_token proves that to POST /auth/mfa. No session cookie yet.
    mfa_required: bool = False
    mfa_token: str | None = None


class MfaVerifyRequest(BaseModel):
    mfa_token: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=6, max_length=20)  # 6 digits or xxxxx-xxxxx


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class MfaDisableRequest(BaseModel):
    """Re-authentication: the password, or a current code for Google-only
    accounts that have none."""

    password: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, min_length=6, max_length=20)


class MfaEnrolOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaRecoveryCodesOut(BaseModel):
    recovery_codes: list[str]
