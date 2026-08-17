"""max_age aging for every signed-token family (M5.7 H3).

The 30-day status TTL is a published GDPR promise (G0 decision, disclosed
in the privacy notice) and the interview 60-day TTL is disclosed alongside
it — until now none of the seven families had expiry coverage.

Seam: itsdangerous stamps tokens via ``time.time()`` looked up through its
``timed`` module, so minting inside a patched-module context produces a
genuinely old token that the *unpatched* read path must reject. No
sleeping, no production-code changes.
"""

import types
import uuid
from collections.abc import Callable
from time import time as real_time

import itsdangerous.timed
import pytest

from app.core import security

DAY = 86400


def _minted_ago(seconds: int, mint: Callable[[], str]) -> str:
    """Run the token factory with itsdangerous' clock wound back."""
    fake = types.SimpleNamespace(time=lambda: real_time() - seconds)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(itsdangerous.timed, "time", fake)
        return mint()


FAMILIES = [
    pytest.param(
        security.SESSION_MAX_AGE_SECONDS,
        lambda: security.create_session_token(uuid.uuid4(), 0),
        security.read_session_token,
        id="session",
    ),
    pytest.param(
        security.QUIZ_TOKEN_MAX_AGE_SECONDS,
        lambda: security.create_quiz_token(uuid.uuid4()),
        security.read_quiz_token,
        id="quiz",
    ),
    pytest.param(
        security.STATUS_TOKEN_MAX_AGE_SECONDS,
        lambda: security.create_status_token(uuid.uuid4()),
        security.read_status_token,
        id="status",
    ),
    pytest.param(
        security.INVITE_TOKEN_MAX_AGE_SECONDS,
        lambda: security.create_invite_token(uuid.uuid4()),
        security.read_invite_token,
        id="invite",
    ),
    pytest.param(
        security.INTERVIEW_TOKEN_MAX_AGE_SECONDS,
        lambda: security.create_interview_token(uuid.uuid4()),
        security.read_interview_token,
        id="interview",
    ),
    pytest.param(
        security.PASSWORD_RESET_MAX_AGE_SECONDS,
        lambda: security.create_password_reset_token(uuid.uuid4(), 0),
        security.read_password_reset_token,
        id="password-reset",
    ),
    pytest.param(
        security.GOOGLE_FLOW_MAX_AGE_SECONDS,
        lambda: security.create_google_flow_token("state", "verifier", "nonce"),
        security.read_google_flow_token,
        id="google-flow",
    ),
    pytest.param(
        security.GOOGLE_SIGNUP_MAX_AGE_SECONDS,
        lambda: security.create_google_signup_token("sub-1", "g@vetd-ci.dev"),
        security.read_google_signup_token,
        id="google-signup",
    ),
]


@pytest.mark.parametrize(("max_age", "mint", "read"), FAMILIES)
def test_token_rejected_past_max_age(
    max_age: int, mint: Callable[[], str], read: Callable[[str], object]
) -> None:
    aged_out = _minted_ago(max_age + 60, mint)
    assert read(aged_out) is None
    # ... while an unexpired token of the same vintage family still reads
    still_valid = _minted_ago(max_age // 2, mint)
    assert read(still_valid) is not None


def test_published_ttls_stay_pinned() -> None:
    """These numbers are promises made outside the codebase — the privacy
    notice, the self-hosting guide, and the G0 minimization decision all
    state them. Changing one is a compliance-copy change, not a tweak."""
    assert security.STATUS_TOKEN_MAX_AGE_SECONDS == 30 * DAY
    assert security.INTERVIEW_TOKEN_MAX_AGE_SECONDS == 60 * DAY
    assert security.QUIZ_TOKEN_MAX_AGE_SECONDS == 30 * DAY
