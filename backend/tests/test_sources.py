"""Application source grammar (spec job posts v2 5.4, decision JP2). One
string column; the same shapes the frontend resolver produces."""

import pytest

from app.core.sources import KNOWN_SOURCES, normalize_source


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("direct", "direct"),
        ("linkedin", "linkedin"),
        ("LinkedIn ", "linkedin"),
        ("google ", "google"),
        ("website", "website"),
        ("link:newsletter", "link:newsletter"),
        ("link:Q4_Push-2", "link:q4_push-2"),
        ("ref:example.com", "ref:example.com"),
        ("ref:news.ycombinator.com", "ref:news.ycombinator.com"),
        ("ref:blog.example.co.uk", "ref:blog.example.co.uk"),
        ("", None),
        (None, None),
        ("other", None),
        ("link:", None),
        ("link:" + "a" * 41, None),
        ("link:has space", None),
        ("ref:evil.example/path?x=1", None),
        ("ref:localhost", None),
        ("ref:" + "a" * 70 + ".com", None),
        ("<script>alert(1)</script>", None),
        ("link:ünïcode", None),
        ("ref:EXAMPLE.COM", "ref:example.com"),
    ],
)
def test_normalize_source(raw: str | None, stored: str | None) -> None:
    assert normalize_source(raw) == stored


def test_submit_schema_never_rejects_a_source() -> None:
    from app.schemas.public import ApplicationSubmit

    base = {"name": "A", "email": "a@example.org"}
    assert ApplicationSubmit(**base, source="x" * 300).source is None
    assert ApplicationSubmit(**base, source=12345).source is None  # type: ignore[arg-type]
    assert ApplicationSubmit(**base, source="linkedin").source == "linkedin"
    assert ApplicationSubmit(**base, source=None).source is None


def test_known_sources_are_the_documented_buckets() -> None:
    assert KNOWN_SOURCES == frozenset(
        {
            "direct",
            "google",
            "linkedin",
            "indeed",
            "facebook",
            "x",
            "glassdoor",
            "xing",
            "stepstone",
            "hn",
            "reddit",
            "github",
            "website",
        }
    )
