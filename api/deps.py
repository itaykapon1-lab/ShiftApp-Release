"""FastAPI Dependencies.

This module provides dependency injection functions for:
- Session ID extraction from cookies
- Database session management
"""

import re
import uuid
from typing import Annotated
from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db as _get_db


# Blocklist of invalid session IDs that should never be accepted
# These are commonly used test/default values that could cause data leakage
BLOCKED_SESSION_IDS = {"default", "test", "", "null", "undefined", "none"}

# UUID v4 regex pattern for validation (prevents session fixation attacks)
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def _is_valid_uuid(session_id: str) -> bool:
    """Check if a session ID is a valid UUID v4 format."""
    return bool(UUID_PATTERN.match(session_id))


def _is_valid_session_id(session_id: str | None) -> bool:
    """Check if a session ID is valid (not blocked, not empty, and valid UUID format)."""
    if not session_id:
        return False
    session_id_clean = session_id.lower().strip()
    if session_id_clean in BLOCKED_SESSION_IDS:
        return False
    # Validate UUID format to prevent session fixation attacks
    return _is_valid_uuid(session_id)


def get_session_id(
    request: Request,
    session_id: Annotated[str | None, Cookie()] = None
) -> str:
    """
    Extracts or generates a session ID from the request.

    First checks request.state (set by middleware), then cookie, then generates new.
    Invalid session IDs (from blocklist) are rejected and a new UUID is generated.

    Args:
        request: FastAPI request object
        session_id: Optional session_id from cookie

    Returns:
        str: The session ID for this request
    """
    # Check if middleware already set it and it's valid
    if hasattr(request.state, "session_id") and _is_valid_session_id(request.state.session_id):
        return request.state.session_id

    # Check cookie and validate against blocklist
    if _is_valid_session_id(session_id):
        return session_id

    # Generate new session ID if not present or invalid
    new_session_id = str(uuid.uuid4())
    # Store in request state so middleware can set the cookie
    request.state.session_id = new_session_id
    return new_session_id


# Type alias for dependency injection
SessionID = Annotated[str, Depends(get_session_id)]
DB = Annotated[Session, Depends(_get_db)]
