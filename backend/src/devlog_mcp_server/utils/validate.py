from __future__ import annotations

from datetime import datetime
from typing import Iterable


ALLOWED_ROLES = {"user", "assistant", "system", "ai"}


def normalize_role(role: str) -> str:
    if role is None:
        return ""
    role_norm = role.strip().lower()
    if role_norm == "ai":
        return "assistant"
    return role_norm


def parse_iso8601(value: str) -> datetime:
    if value is None:
        raise ValueError("timestamp is required")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v)


def require_non_empty(value: str, field_name: str) -> None:
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field_name} is required")


def validate_roles(roles: Iterable[str]) -> None:
    for role in roles:
        if role not in ALLOWED_ROLES:
            raise ValueError(f"invalid role: {role}")
