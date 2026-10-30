"""FastAPI dependencies for resolving authenticated human users."""

import auth_tokens
from database import get_session
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from models import User
from sqlmodel import Session

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),  # noqa: B008 - FastAPI dependency marker.
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
) -> User:
    """Resolve a bearer access token to its current user row."""
    unauthorized_headers = {"WWW-Authenticate": "Bearer"}
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers=unauthorized_headers,
        )

    try:
        claims = auth_tokens.decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
    except (auth_tokens.AuthTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers=unauthorized_headers,
        ) from exc

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers=unauthorized_headers,
        )
    return user
