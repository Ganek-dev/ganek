"""SAML 2.0 service provider foundation (card "SAML 2.0 sign-in (ee/)", slice 1).

This slice pins the library (python3-saml on the xmlsec and lxml wheels),
checks that both native bindings load one libxml2, and builds the hardened
SP settings and the SP metadata document the later slices serve. It mounts
no route and validates no assertion: the ACS endpoint, replay guard and
account match land in later slices, each reviewed by the owner before merge.

The settings are strict on purpose. Later slices must not loosen them:
signed assertions only, SHA-256, deprecated algorithms (SHA-1) refused,
unsolicited (IdP-initiated) responses refused via the request id check.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import lxml.etree
import xmlsec
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.settings import OneLogin_Saml2_Settings

API_PREFIX = "/api/v1"
METADATA_PATH = f"{API_PREFIX}/auth/saml/metadata"
ACS_PATH = f"{API_PREFIX}/auth/saml/acs"


class SamlConfigError(RuntimeError):
    """The SAML stack or its configuration cannot be used safely."""


def check_native_bindings() -> None:
    """Refuse to run SAML when lxml and xmlsec load different libxml2 builds.

    That mismatch is the most reported python3-saml failure: signature
    checks crash or misbehave at runtime instead of failing at install.
    """
    lxml_version = tuple(lxml.etree.LIBXML_VERSION)
    xmlsec_version = tuple(xmlsec.get_libxml_version())
    if lxml_version != xmlsec_version:
        raise SamlConfigError(
            f"lxml uses libxml2 {lxml_version} but xmlsec uses {xmlsec_version}; "
            "install matching lxml and xmlsec wheels"
        )


@dataclass(frozen=True)
class IdpConfig:
    """What an admin pastes from the IdP: entity id, SSO URL, signing cert."""

    entity_id: str
    sso_url: str
    x509_cert: str


def sp_entity_id(base_url: str) -> str:
    """The SP entity id is its metadata URL, the common convention."""
    return f"{base_url.rstrip('/')}{METADATA_PATH}"


def acs_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{ACS_PATH}"


def _security() -> dict[str, Any]:
    return {
        "strict": True,
        "authnRequestsSigned": False,
        "logoutRequestSigned": False,
        "logoutResponseSigned": False,
        "signMetadata": False,
        "wantMessagesSigned": False,
        # Every assertion must carry its own valid signature; a signed
        # Response around an unsigned assertion is not enough.
        "wantAssertionsSigned": True,
        "wantAssertionsEncrypted": False,
        "wantNameId": True,
        "wantNameIdEncrypted": False,
        "wantAttributeStatement": False,
        "requestedAuthnContext": False,
        "rejectUnsolicitedResponsesWithInResponseTo": True,
        "rejectDeprecatedAlgorithm": True,
        "allowRepeatAttributeName": False,
        "signatureAlgorithm": C.RSA_SHA256,
        "digestAlgorithm": C.SHA256,
    }


def build_settings_dict(base_url: str, idp: IdpConfig) -> dict[str, Any]:
    if not idp.x509_cert.strip():
        raise SamlConfigError("the IdP signing certificate is required")
    for name, url in (("SSO URL", idp.sso_url), ("base URL", base_url)):
        if not url.startswith("https://") and not url.startswith("http://localhost"):
            raise SamlConfigError(f"the {name} must use https")
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": sp_entity_id(base_url),
            "assertionConsumerService": {
                "url": acs_url(base_url),
                "binding": C.BINDING_HTTP_POST,
            },
            "NameIDFormat": C.NAMEID_UNSPECIFIED,
            "x509cert": "",
            "privateKey": "",
        },
        "idp": {
            "entityId": idp.entity_id,
            "singleSignOnService": {
                "url": idp.sso_url,
                "binding": C.BINDING_HTTP_REDIRECT,
            },
            "x509cert": idp.x509_cert,
        },
        "security": _security(),
    }


def build_settings(base_url: str, idp: IdpConfig) -> OneLogin_Saml2_Settings:
    check_native_bindings()
    try:
        return OneLogin_Saml2_Settings(build_settings_dict(base_url, idp), sp_validation_only=False)
    except Exception as exc:  # the toolkit raises its own error type with a code
        raise SamlConfigError(f"invalid SAML settings: {exc}") from exc


def sp_metadata(base_url: str) -> bytes:
    """SP metadata XML for the IdP admin: entity id, ACS URL and binding."""
    check_native_bindings()
    sp_only: Mapping[str, Any] = {
        "strict": True,
        "sp": {
            "entityId": sp_entity_id(base_url),
            "assertionConsumerService": {
                "url": acs_url(base_url),
                "binding": C.BINDING_HTTP_POST,
            },
            "NameIDFormat": C.NAMEID_UNSPECIFIED,
        },
        "security": _security(),
    }
    settings = OneLogin_Saml2_Settings(dict(sp_only), sp_validation_only=True)
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        raise SamlConfigError(f"generated SP metadata is invalid: {errors}")
    return metadata if isinstance(metadata, bytes) else metadata.encode()
