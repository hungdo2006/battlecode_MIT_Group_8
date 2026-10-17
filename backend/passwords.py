"""Password primitives only; no HTTP authentication is enabled in Phase B.1."""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


# Explicit RFC 9106 low-memory profile: 64 MiB, 3 iterations, 4 lanes.
# Never pass a manual salt; argon2-cffi generates a fresh random one per hash.
_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
                         hash_len=32, salt_len=16, type=Type.ID)
MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_BYTES = 1024


def validate_new_password(password: str):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must contain at least {MIN_PASSWORD_LENGTH} characters")
    try:
        size = len(password.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError("Password must be valid UTF-8 text") from None
    if size > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes")


def hash_password(password: str) -> str:
    validate_new_password(password)
    return _HASHER.hash(password)


def verify_password(encoded_hash: str, password: str) -> bool:
    # Hashes must come from our trusted database, never from a client request.
    if (not isinstance(encoded_hash, str) or not encoded_hash.startswith("$argon2id$")
            or not isinstance(password, str)):
        return False
    try:
        if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            return False
        return _HASHER.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, UnicodeEncodeError):
        return False


def needs_rehash(encoded_hash: str) -> bool:
    return _HASHER.check_needs_rehash(encoded_hash)
