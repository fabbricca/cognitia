"""Security utilities for authentication."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
import jwt
from pydantic import BaseModel


# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret_change_in_production")
JWT_ALGORITHM = "HS256"


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # User ID
    email: str
    role: str
    type: str  # "access" or "refresh"
    exp: int  # Expiration timestamp
    iat: int  # Issued at timestamp


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def create_jwt_token(
    user_id: UUID,
    email: str,
    role: str,
    token_type: str = "access",
    expires_minutes: Optional[int] = None,
    expires_days: Optional[int] = None,
) -> str:
    """
    Create JWT token.

    Args:
        user_id: User UUID
        email: User email
        role: User role (user, admin)
        token_type: "access" or "refresh"
        expires_minutes: Token expiry in minutes (for access tokens)
        expires_days: Token expiry in days (for refresh tokens)

    Returns:
        Encoded JWT token
    """
    now = datetime.now(timezone.utc)

    # Calculate expiration
    if expires_minutes:
        exp = now + timedelta(minutes=expires_minutes)
    elif expires_days:
        exp = now + timedelta(days=expires_days)
    else:
        # Default: access=1h, refresh=30d
        if token_type == "access":
            exp = now + timedelta(hours=1)
        else:
            exp = now + timedelta(days=30)

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": token_type,
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> TokenPayload:
    """
    Decode and verify JWT token.

    Raises:
        jwt.ExpiredSignatureError: Token expired
        jwt.InvalidTokenError: Token invalid
    """
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    return TokenPayload(**payload)


def verify_jwt_token(token: str, expected_type: str = "access") -> Optional[TokenPayload]:
    """
    Verify JWT token and return payload if valid.

    Args:
        token: JWT token string
        expected_type: Expected token type ("access" or "refresh")

    Returns:
        TokenPayload if valid, None if invalid
    """
    try:
        payload = decode_jwt_token(token)
        if payload.type != expected_type:
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
