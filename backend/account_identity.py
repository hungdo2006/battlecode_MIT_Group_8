"""Shared canonical identity rules for offline bootstrap and account services."""
import re


def normalize_username(username: str) -> str:
    if not isinstance(username, str):
        raise ValueError("Username must be text")
    result = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", result, flags=re.ASCII):
        raise ValueError("Username must be 3..32 ASCII letters, digits, '.', '_' or '-'")
    return result


def display_name(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 64 or "\0" in value:
        raise ValueError("Display name must contain 1..64 characters without NUL")
    return value.strip()
