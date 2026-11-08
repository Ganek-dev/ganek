"""Custom careers domains (board card "Custom domains + subdomain routing",
slice 2): an admin claims a domain such as ``careers.acme.com``, publishes a
DNS TXT record carrying the company's token, and the check marks the domain
verified. Only a verified domain may ever route (the Host routing slice
reads ``verified_domain``); a pending claim proves nothing and locks nothing.

Which plans may use a custom domain is the plan policy's call
(``PlanPolicy.custom_domains``): self-hosters already serve on their own
domain, hosted tenants get it on Team (BM3).
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import urls
from app.models import Company

# the record an admin publishes: <TXT_PREFIX>.<domain> TXT "<TXT_VALUE_PREFIX><token>"
TXT_PREFIX = "_ganek"
TXT_VALUE_PREFIX = "ganek-domain-verification="
DNS_TIMEOUT_SECONDS = 5.0

DomainStatus = Literal["none", "pending", "verified"]

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class InvalidDomain(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DomainTaken(Exception):
    """Another company already verified this domain."""


class VerificationFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _platform_hosts() -> set[str]:
    """The instance's own host and, when that host is a subdomain
    (app.ganek.io), its parent (ganek.io): tenant subdomains live there, so
    no tenant may claim any name under either."""
    host = urls.instance_host()
    hosts = {host} if host else set()
    labels = host.split(".")
    if len(labels) >= 3:
        hosts.add(".".join(labels[1:]))
    return hosts


def normalize_domain(raw: str) -> str:
    """A bare hostname, lowercase, ASCII (IDNA), no trailing dot. Refuses
    URLs, ports, IP addresses, single labels and the instance's own domain."""
    value = raw.strip().lower().rstrip(".")
    if not value:
        raise InvalidDomain("Enter a domain such as careers.example.com")
    if any(ch in value for ch in "/:@?# "):
        raise InvalidDomain("Enter the domain only, without https:// or a path")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError:
        raise InvalidDomain("This is not a valid domain name") from None
    labels = value.split(".")
    if len(value) > 253 or len(labels) < 2 or not all(_LABEL.match(lb) for lb in labels):
        raise InvalidDomain("This is not a valid domain name")
    if labels[-1].isdigit():
        raise InvalidDomain("Use a domain name, not an IP address")
    if value == "localhost" or value.endswith(".localhost"):
        raise InvalidDomain("This is not a public domain")
    for platform in _platform_hosts():
        if value == platform or value.endswith("." + platform):
            raise InvalidDomain("Domains of this instance cannot be used as a custom domain")
    return value


def txt_record_name(domain: str) -> str:
    return f"{TXT_PREFIX}.{domain}"


def txt_record_value(token: str) -> str:
    return f"{TXT_VALUE_PREFIX}{token}"


def status(company: Company) -> DomainStatus:
    if not company.custom_domain:
        return "none"
    return "verified" if company.custom_domain_verified_at is not None else "pending"


def verified_domain(company: Company) -> str | None:
    """The domain the routing slice may serve the careers page on, if any."""
    if company.custom_domain and company.custom_domain_verified_at is not None:
        return company.custom_domain
    return None


async def lookup_txt(name: str) -> list[str]:
    """TXT strings published at ``name``; empty when there are none.
    Tests replace this function; DNS errors surface as VerificationFailed."""
    import dns.asyncresolver
    import dns.exception
    import dns.resolver

    try:
        answer = await dns.asyncresolver.resolve(name, "TXT", lifetime=DNS_TIMEOUT_SECONDS)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        raise VerificationFailed(
            "The DNS lookup did not answer. Try again in a few minutes."
        ) from None
    out: list[str] = []
    for record in answer:
        strings = getattr(record, "strings", ())
        out.append(b"".join(strings).decode("utf-8", "replace"))
    return out


async def set_domain(db: AsyncSession, company: Company, raw: str) -> Company:
    """Claim (or replace) the company's domain. A new or changed domain gets
    a fresh token and starts pending; re-sending the same domain keeps both
    the token and any verification."""
    domain = normalize_domain(raw)
    if domain != company.custom_domain:
        company.custom_domain = domain
        company.custom_domain_token = secrets.token_hex(16)
        company.custom_domain_verified_at = None
        await db.commit()
        await db.refresh(company)
    return company


async def remove_domain(db: AsyncSession, company: Company) -> Company:
    company.custom_domain = None
    company.custom_domain_token = None
    company.custom_domain_verified_at = None
    await db.commit()
    await db.refresh(company)
    return company


async def verify_domain(db: AsyncSession, company: Company) -> Company:
    """Look up the TXT record and mark the domain verified when it carries
    this company's token. Raises VerificationFailed with a message the admin
    can act on, DomainTaken when another company verified it first."""
    domain, token = company.custom_domain, company.custom_domain_token
    if not domain or not token:
        raise VerificationFailed("Add a custom domain first")
    if company.custom_domain_verified_at is not None:
        return company
    expected = txt_record_value(token)
    found = await lookup_txt(txt_record_name(domain))
    if expected not in (value.strip() for value in found):
        raise VerificationFailed(
            f"No TXT record {txt_record_name(domain)} with the value {expected} was found "
            "yet. DNS changes can take up to an hour to show."
        )
    holder = (
        await db.execute(
            select(Company.id).where(
                Company.custom_domain == domain,
                Company.custom_domain_verified_at.is_not(None),
                Company.id != company.id,
            )
        )
    ).scalar_one_or_none()
    if holder is not None:
        raise DomainTaken()
    company.custom_domain_verified_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(company)
    return company
