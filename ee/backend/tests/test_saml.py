"""SAML slice 1: native deps, hardened settings, SP metadata. No assertion
validation exists yet, so there is nothing to sign or replay here."""

import lxml.etree
import pytest

from ganek_ee import saml

BASE = "https://hire.example.com"
MD = "{urn:oasis:names:tc:SAML:2.0:metadata}"

# A placeholder certificate string: slice 1 stores it but never parses it.
IDP_CERT = (
    "MIIBnzCCAQgCCQCnU2uMp3kXzDANBgkqhkiG9w0BAQsFADAUMRIwEAYDVQQDDAl0ZXN0LWlk"
    "cDAeFw0yNjAxMDEwMDAwMDBaFw0zNjAxMDEwMDAwMDBaMBQxEjAQBgNVBAMMCXRlc3QtaWRw"
)


def idp(**overrides: str) -> saml.IdpConfig:
    values = {
        "entity_id": "https://idp.example.org/metadata",
        "sso_url": "https://idp.example.org/sso",
        "x509_cert": IDP_CERT,
    }
    values.update(overrides)
    return saml.IdpConfig(**values)


def test_lxml_and_xmlsec_share_one_libxml2() -> None:
    saml.check_native_bindings()


def test_mismatched_libxml2_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saml.xmlsec, "get_libxml_version", lambda: (1, 0, 0))
    with pytest.raises(saml.SamlConfigError, match="libxml2"):
        saml.check_native_bindings()


def test_urls_follow_the_api_prefix_and_ignore_a_trailing_slash() -> None:
    assert saml.sp_entity_id(BASE + "/") == BASE + "/api/v1/auth/saml/metadata"
    assert saml.acs_url(BASE) == BASE + "/api/v1/auth/saml/acs"


def test_security_settings_are_strict() -> None:
    d = saml.build_settings_dict(BASE, idp())
    sec = d["security"]
    assert d["strict"] is True and d["debug"] is False
    assert sec["wantAssertionsSigned"] is True
    assert sec["wantNameId"] is True
    assert sec["rejectDeprecatedAlgorithm"] is True
    assert sec["rejectUnsolicitedResponsesWithInResponseTo"] is True
    assert sec["allowRepeatAttributeName"] is False
    assert sec["signatureAlgorithm"].endswith("rsa-sha256")
    assert sec["digestAlgorithm"].endswith("sha256")


def test_toolkit_accepts_the_settings() -> None:
    settings = saml.build_settings(BASE, idp())
    assert settings.is_strict()
    assert settings.get_security_data()["wantAssertionsSigned"] is True
    assert settings.get_idp_data()["entityId"] == "https://idp.example.org/metadata"


def test_missing_idp_certificate_is_refused() -> None:
    with pytest.raises(saml.SamlConfigError, match="certificate"):
        saml.build_settings_dict(BASE, idp(x509_cert="  "))


@pytest.mark.parametrize("field", ["sso_url", "base"])
def test_plain_http_is_refused(field: str) -> None:
    base = "http://hire.example.com" if field == "base" else BASE
    config = idp(sso_url="http://idp.example.org/sso") if field == "sso_url" else idp()
    with pytest.raises(saml.SamlConfigError, match="https"):
        saml.build_settings_dict(base, config)


def test_localhost_http_is_allowed_for_development() -> None:
    d = saml.build_settings_dict("http://localhost:3000", idp())
    assert d["sp"]["assertionConsumerService"]["url"] == (
        "http://localhost:3000/api/v1/auth/saml/acs"
    )


def test_sp_metadata_names_entity_id_and_post_acs() -> None:
    root = lxml.etree.fromstring(saml.sp_metadata(BASE))
    assert root.tag == MD + "EntityDescriptor"
    assert root.get("entityID") == BASE + "/api/v1/auth/saml/metadata"
    sp = root.find(MD + "SPSSODescriptor")
    assert sp is not None
    assert sp.get("WantAssertionsSigned") == "true"
    acs = sp.find(MD + "AssertionConsumerService")
    assert acs is not None
    assert acs.get("Location") == BASE + "/api/v1/auth/saml/acs"
    assert acs.get("Binding") == "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"


def test_sp_metadata_has_no_doctype_or_entities() -> None:
    xml = saml.sp_metadata(BASE)
    assert b"<!DOCTYPE" not in xml and b"<!ENTITY" not in xml
