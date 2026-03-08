"""Factory helpers for deterministic test identities and payloads."""

import uuid


def make_unique_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def make_session_id(prefix: str = "test-session") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

