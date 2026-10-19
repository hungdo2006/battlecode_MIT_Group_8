"""Admin MFA: RFC 6238 TOTP (HMAC-SHA1, 30-second steps, 6 digits).

Secret provisioning belongs to offline CLI, never the HTTP API. A code is
single-use across all sessions by storing the accepted counter in SQLite.
"""
import base64
import hashlib
import hmac
import re
import secrets


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def code_at(secret, counter):
    key = base64.b32decode(secret, casefold=False)
    signature = hmac.digest(key, int(counter).to_bytes(8, "big"), hashlib.sha1)
    pos = signature[-1] & 15
    value = int.from_bytes(signature[pos:pos + 4], "big") & 0x7fffffff
    return f"{value % 1000000:06d}"


def accepted_counter(secret, supplied, now, last_counter):
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9]{6}", supplied, re.ASCII):
        return None
    current = int(now) // 30
    # Avoid ever accepting an OTP counter a previous login has consumed.
    for count in (current - 1, current, current + 1):
        if count >= 0 and count > last_counter and hmac.compare_digest(code_at(secret, count), supplied):
            return count
    return None
