import re
import secrets


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:64] or "item"


def with_random_suffix(base: str) -> str:
    return f"{base[:57]}-{secrets.token_hex(3)}"
