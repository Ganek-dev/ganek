import uuid

from app.core.security import (
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)
from app.services.slugs import slugify


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_verify_rejects_garbage_hash() -> None:
    assert not verify_password("anything", "not-a-valid-argon2-hash")


def test_session_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(user_id, 0)
    assert read_session_token(token) == (user_id, 0)


def test_session_token_rejects_tampering() -> None:
    token = create_session_token(uuid.uuid4(), 2)
    assert read_session_token(token[:-2] + "xx") is None
    assert read_session_token("completely-bogus") is None


def test_slugify() -> None:
    assert slugify("Acme Inc.") == "acme-inc"
    assert slugify("  Über  Cool GmbH!  ") == "ber-cool-gmbh"
    assert slugify("!!!") == "item"
    assert len(slugify("x" * 300)) <= 64
