import re
import secrets


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:64] or "item"


def with_random_suffix(base: str) -> str:
    return f"{base[:57]}-{secrets.token_hex(3)}"


# Company slugs become tenant subdomains on a hosted multi-mode instance
# (<slug>.ganek.io, decision 2026-10-24). These names belong to the platform
# itself (admin host, API, mail, status, docs, the demo) and must never be a
# tenant, or a signup could pose as Ganek on our own domain. Compared with
# hyphens removed, so "a-p-i" or "help-" cannot slip through.
RESERVED_COMPANY_SLUGS: frozenset[str] = frozenset(
    {
        "app",
        "api",
        "www",
        "admin",
        "login",
        "mail",
        "status",
        "docs",
        "help",
        "billing",
        "demo",
        # close variants of the above
        "apps",
        "www1",
        "www2",
        "administrator",
        "signin",
        "signup",
        "register",
        "logout",
        "auth",
        "oauth",
        "sso",
        "account",
        "accounts",
        "email",
        "smtp",
        "imap",
        "pop",
        "pop3",
        "mx",
        "webmail",
        "statuspage",
        "doc",
        "documentation",
        "support",
        "billings",
        "invoice",
        "invoices",
        "pay",
        "payment",
        "payments",
        "demos",
        "ops",
        "root",
        "superadmin",
        "security",
        "static",
        "assets",
        "cdn",
        "media",
        "dashboard",
        "internal",
        "staging",
        "dev",
        "localhost",
    }
)

# Brand names: any slug that contains one of these is refused, so "ganek",
# "ganek-io", "get-ganek" or "ganekhq" can never be a tenant host.
RESERVED_BRAND_WORDS: tuple[str, ...] = ("ganek", "vetd")


def is_reserved_company_slug(slug: str) -> bool:
    """True when ``slug`` may never be a company (tenant subdomain) slug."""
    compact = slug.replace("-", "").lower()
    if compact in RESERVED_COMPANY_SLUGS:
        return True
    return any(word in compact for word in RESERVED_BRAND_WORDS)
