"""Milestone 1 auth: a static bearer token from the environment.

Replaced by Supabase Auth JWT verification when the dashboard is built.
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.api_token:
        # Fail closed: never serve private data when no token is configured.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_TOKEN is not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.api_token.encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
