"""Generic OIDC: pure logic (discovery validation, claim checks, email
linking rule, flow token). No database, no network."""

import time

import pytest

from app.core.config import settings
from app.core.security import create_oidc_flow_token, read_oidc_flow_token
from app.services import oauth_oidc

ISSUER = "https://idp.example.com/realms/acme"


@pytest.fixture(autouse=True)
def oidc_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", "ganek")
    monkeypatch.setattr(settings, "oidc_client_secret", "s3cret")
    monkeypatch.setattr(settings, "oidc_email_domains", "acme.test, @Example.org")


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": "ganek",
        "exp": time.time() + 600,
        "nonce": "n-1",
        "sub": "sub-1",
        "email": "ana@acme.test",
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


def test_configured_needs_issuer_id_and_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    assert oauth_oidc.configured()
    monkeypatch.setattr(settings, "oidc_client_secret", None)
    assert not oauth_oidc.configured()


def test_email_domains_are_normalised() -> None:
    assert oauth_oidc.email_domains() == {"acme.test", "example.org"}


def test_discovery_accepts_matching_issuer_with_trailing_slash() -> None:
    meta = oauth_oidc.parse_discovery(
        {
            "issuer": ISSUER + "/",
            "authorization_endpoint": f"{ISSUER}/auth",
            "token_endpoint": f"{ISSUER}/token",
        }
    )
    assert (meta.authorization_endpoint, meta.token_endpoint) == (
        f"{ISSUER}/auth",
        f"{ISSUER}/token",
    )


@pytest.mark.parametrize(
    "doc",
    [
        [],
        {
            "issuer": "https://evil.test",
            "authorization_endpoint": "https://a",
            "token_endpoint": "https://t",
        },
        {
            "issuer": ISSUER,
            "authorization_endpoint": "http://idp.example.com/auth",
            "token_endpoint": f"{ISSUER}/token",
        },
        {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/auth"},
        {
            "issuer": ISSUER,
            "authorization_endpoint": "javascript:alert(1)",
            "token_endpoint": f"{ISSUER}/token",
        },
    ],
)
def test_discovery_rejects_bad_documents(doc: object) -> None:
    with pytest.raises(oauth_oidc.OidcError):
        oauth_oidc.parse_discovery(doc)


def test_discovery_allows_plain_http_for_a_local_test_idp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_issuer", "http://localhost:8080/realms/test")
    meta = oauth_oidc.parse_discovery(
        {
            "issuer": "http://localhost:8080/realms/test",
            "authorization_endpoint": "http://localhost:8080/realms/test/auth",
            "token_endpoint": "http://localhost:8080/realms/test/token",
        }
    )
    assert meta.token_endpoint.startswith("http://localhost")


def test_authorization_request_uses_pkce_and_minimal_scope() -> None:
    meta = oauth_oidc.ProviderMetadata(ISSUER, f"{ISSUER}/auth?kc_idp_hint=x", f"{ISSUER}/token")
    url, state, verifier, nonce = oauth_oidc.build_authorization_request(meta)
    assert url.startswith(f"{ISSUER}/auth?kc_idp_hint=x&")
    assert "code_challenge_method=S256" in url
    assert "scope=openid+email" in url
    assert f"state={state}" in url and f"nonce={nonce}" in url
    assert verifier not in url


def test_valid_claims_pass() -> None:
    oauth_oidc.validate_claims(_claims(), nonce="n-1")
    oauth_oidc.validate_claims(_claims(iss=ISSUER + "/"), nonce="n-1")
    oauth_oidc.validate_claims(_claims(aud=["ganek"]), nonce="n-1")
    oauth_oidc.validate_claims(_claims(aud=["ganek", "api"], azp="ganek"), nonce="n-1")


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.test"},
        {"aud": "someone-else"},
        {"aud": ["someone-else"]},
        {"aud": ["ganek", "api"]},  # several audiences without azp
        {"azp": "someone-else"},
        {"exp": time.time() - 1},
        {"exp": True},
        {"nonce": "other"},
        {"nonce": None},
        {"sub": ""},
        {"sub": 42},
    ],
)
def test_invalid_claims_fail(overrides: dict[str, object]) -> None:
    with pytest.raises(oauth_oidc.OidcError):
        oauth_oidc.validate_claims(_claims(**overrides), nonce="n-1")


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"email": "Ana@ACME.test"}, True),
        ({"email_verified": "true"}, True),
        ({"email": "bob@example.org"}, True),
        ({"email_verified": False}, False),
        ({"email_verified": "false"}, False),
        ({"email_verified": None}, False),
        ({"email": "ana@gmail.com"}, False),  # IdP not trusted for this domain
        ({"email": "ana@sub.acme.test"}, False),  # exact domain only
        ({"email": "not-an-email"}, False),
        ({"email": None}, False),
    ],
)
def test_email_linkable(overrides: dict[str, object], expected: bool) -> None:
    assert oauth_oidc.email_linkable(_claims(**overrides)) is expected


def test_no_domains_means_no_linking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_email_domains", "")
    assert oauth_oidc.email_linkable(_claims()) is False


def test_flow_token_round_trip_and_unsafe_next() -> None:
    token = create_oidc_flow_token("s", "v", "n", next_path="/invite/abc")
    assert read_oidc_flow_token(token) == ("s", "v", "n", "/invite/abc", None)
    assert read_oidc_flow_token(create_oidc_flow_token("s", "v", "n")) == (
        "s",
        "v",
        "n",
        None,
        None,
    )
    # a signed but unsafe target is dropped on read
    from app.core import security

    forged = security._oidc_flow_serializer.dumps(
        {"s": "s", "cv": "v", "n": "n", "x": "https://evil.test"}
    )
    assert read_oidc_flow_token(forged) == ("s", "v", "n", None, None)
    assert read_oidc_flow_token("garbage") is None


def test_flow_token_carries_an_invite() -> None:
    token = create_oidc_flow_token("s", "v", "n", invite="inv.tok-1")
    assert read_oidc_flow_token(token) == ("s", "v", "n", None, "inv.tok-1")


def test_invite_email_match_needs_same_verified_email() -> None:
    from app.api.oidc_auth import oidc_email_matches

    def claims(email: object, verified: object) -> dict[str, object]:
        return {"email": email, "email_verified": verified}

    assert oidc_email_matches(claims("Ann@Corp.dev", True), "ann@corp.dev") is True
    assert oidc_email_matches(claims("ann@corp.dev", "true"), "ann@corp.dev") is True
    assert oidc_email_matches(claims("ann@corp.dev", False), "ann@corp.dev") is False
    assert oidc_email_matches(claims("ann@corp.dev", "false"), "ann@corp.dev") is False
    assert oidc_email_matches(claims("ann@corp.dev", None), "ann@corp.dev") is False
    assert oidc_email_matches(claims("bob@corp.dev", True), "ann@corp.dev") is False
    assert oidc_email_matches(claims(None, True), "ann@corp.dev") is False
    # the domain list guards linking only: an unlisted domain may accept its own invite
    assert oidc_email_matches(claims("ann@gmail.com", True), "ann@gmail.com") is True


def test_google_flow_token_is_not_an_oidc_flow_token() -> None:
    from app.core.security import create_google_flow_token

    assert read_oidc_flow_token(create_google_flow_token("s", "v", "n")) is None
