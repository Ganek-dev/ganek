"""ALTCHA v1 proof-of-work protocol (board card A5): create, solve, verify."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import pytest
from fastapi import HTTPException

from app.core import challenge, ratelimit
from app.core.config import settings


@pytest.fixture
def captcha_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "captcha_enabled", True)
    monkeypatch.setattr(settings, "captcha_secret", "s3cret")
    monkeypatch.setattr(settings, "captcha_max_number", 2_000)
    monkeypatch.setattr(ratelimit, "_get_redis", lambda: None)


def solve(item: dict[str, Any]) -> str:
    """What the widget does: brute-force the number, send base64 JSON."""
    for number in range(int(item["maxnumber"]) + 1):
        if hashlib.sha256(f"{item['salt']}{number}".encode()).hexdigest() == item["challenge"]:
            payload = {
                "algorithm": item["algorithm"],
                "challenge": item["challenge"],
                "number": number,
                "salt": item["salt"],
                "signature": item["signature"],
            }
            return base64.b64encode(json.dumps(payload).encode()).decode()
    raise AssertionError("unsolvable challenge")


def test_inactive_unless_enabled_with_secret_in_multi_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "captcha_enabled", True)
    monkeypatch.setattr(settings, "captcha_secret", "s3cret")
    monkeypatch.setattr(settings, "mode", "single")
    assert challenge.active() is False
    monkeypatch.setattr(settings, "mode", "multi")
    assert challenge.active() is True
    monkeypatch.setattr(settings, "captcha_secret", None)
    assert challenge.active() is False  # enabled without a key stays off (logged)
    monkeypatch.setattr(settings, "captcha_enabled", False)
    assert challenge.active() is False


def test_challenge_shape_and_round_trip(captcha_on: None) -> None:
    item = challenge.create(now=1_000_000)
    assert set(item) == {"algorithm", "challenge", "maxnumber", "salt", "signature"}
    assert item["algorithm"] == "SHA-256"
    assert item["maxnumber"] == 2_000
    assert item["salt"].endswith(f"?expires={1_000_000 + settings.captcha_ttl_seconds}&")
    payload = solve(item)
    assert challenge.verify(payload, now=1_000_000) is True


def test_verify_rejects_expired_forged_and_malformed(captcha_on: None) -> None:
    item = challenge.create(now=1_000_000)
    payload = solve(item)
    assert challenge.verify(payload, now=1_000_000 + settings.captcha_ttl_seconds + 1) is False

    decoded = json.loads(base64.b64decode(payload))
    wrong_number = dict(decoded, number=decoded["number"] + 1)
    assert challenge.verify(base64.b64encode(json.dumps(wrong_number).encode()).decode()) is False
    # a forged challenge/number pair with no valid HMAC
    salt = decoded["salt"]
    forged_hash = hashlib.sha256(f"{salt}7".encode()).hexdigest()
    forged = dict(decoded, number=7, challenge=forged_hash)
    assert challenge.verify(base64.b64encode(json.dumps(forged).encode()).decode()) is False
    # a payload signed with another instance's secret
    other = dict(decoded, signature="0" * 64)
    assert challenge.verify(base64.b64encode(json.dumps(other).encode()).decode()) is False

    assert challenge.verify("not base64 at all!") is False
    assert challenge.verify(base64.b64encode(b"[1,2]").decode()) is False
    assert challenge.verify(base64.b64encode(b'{"algorithm":"SHA-256"}').decode()) is False


async def test_require_maps_to_stable_422_details(captcha_on: None) -> None:
    with pytest.raises(HTTPException) as missing:
        await challenge.require(None)
    assert (missing.value.status_code, missing.value.detail) == (422, "captcha-required")
    with pytest.raises(HTTPException) as bad:
        await challenge.require("garbage")
    assert (bad.value.status_code, bad.value.detail) == (422, "captcha-invalid")
    await challenge.require(solve(challenge.create()))  # no raise


async def test_require_is_a_noop_while_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "captcha_enabled", False)
    await challenge.require(None)
    await challenge.require("garbage")


async def test_solved_payload_is_single_use_with_redis(
    captcha_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.keys: set[str] = set()

        async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> Any:
            if nx and key in self.keys:
                return None
            self.keys.add(key)
            return True

    redis = FakeRedis()
    monkeypatch.setattr(ratelimit, "_get_redis", lambda: redis)
    payload = solve(challenge.create())
    await challenge.require(payload)
    with pytest.raises(HTTPException) as replay:
        await challenge.require(payload)
    assert replay.value.detail == "captcha-invalid"
    assert len(redis.keys) == 1
