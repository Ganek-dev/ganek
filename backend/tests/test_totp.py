"""TOTP and recovery-code primitives (board card A6), RFC 6238 test vector
plus the replay and drift rules."""

import base64

from app.core import totp


def test_rfc6238_sha1_vector() -> None:
    # RFC 6238 appendix B, SHA-1 secret "12345678901234567890", T = 59 s -> step 1
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp._code_at(secret, 1) == "287082"  # the 8-digit vector 94287082, last six
    assert totp.verify_code(secret, "287082", now=59) == 1
    assert totp.verify_code(secret, "287 082", now=59) == 1  # spaces tolerated


def test_drift_window_and_replay() -> None:
    secret = totp.new_secret()
    now = 1_700_000_000
    step = totp.current_step(now)
    code = totp._code_at(secret, step)
    assert totp.verify_code(secret, code, now=now) == step
    assert totp.verify_code(secret, code, now=now + 30) == step  # one step of drift
    assert totp.verify_code(secret, code, now=now - 30) == step
    assert totp.verify_code(secret, code, now=now + 90) is None
    # the step that already logged someone in never matches again
    assert totp.verify_code(secret, code, last_step=step, now=now) is None
    assert (
        totp.verify_code(secret, "000000", now=now) in (None, step)
        and totp.verify_code(secret, "12345", now=now) is None
    )


def test_provisioning_uri_names_issuer_and_account() -> None:
    uri = totp.provisioning_uri("ABC234", account="erika@northwind.example")
    assert uri.startswith("otpauth://totp/Ganek%3Aerika%40northwind.example?secret=ABC234")
    assert "issuer=Ganek" in uri and "digits=6" in uri and "period=30" in uri


def test_recovery_codes_are_single_use_and_hashed() -> None:
    codes = totp.new_recovery_codes()
    assert len(codes) == totp.RECOVERY_CODE_COUNT == len(set(codes))
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    hashes = [totp.hash_recovery_code(c) for c in codes]
    assert codes[0] not in hashes
    remaining = totp.consume_recovery_code(hashes, codes[0].upper())  # case-insensitive
    assert remaining is not None and len(remaining) == len(hashes) - 1
    assert totp.consume_recovery_code(remaining, codes[0]) is None
    assert totp.consume_recovery_code(remaining, "nope-nope") is None
