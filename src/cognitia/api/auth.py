"""Authentication utilities.

This package no longer issues tokens. Tokens are issued by the dedicated
`cognitia-auth` service using RS256 and published via JWKS.
"""

import base64
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import bcrypt
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import User, get_session

security = HTTPBearer()

JWKS_URL = os.getenv("JWKS_URL", "https://auth.cognitia.iberu.me/.well-known/jwks.json")
JWT_ISSUER = os.getenv("JWT_ISSUER", "https://auth.cognitia.iberu.me").rstrip("/")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "cognitia-api")

_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "jwks": None}
_JWKS_TTL_SECONDS = int(os.getenv("JWKS_CACHE_TTL_SECONDS", "300"))


class TokenPayload(BaseModel):
    sub: str
    email: Optional[str] = None
    exp: datetime
    type: str
    iss: Optional[str] = None
    aud: Optional[str] = None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def _b64url_to_int(val: str) -> int:
    padded = val + "=" * (-len(val) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return int.from_bytes(raw, byteorder="big")


def _rsa_public_key_from_jwk(jwk: Dict[str, Any]) -> rsa.RSAPublicKey:
    if jwk.get("kty") != "RSA":
        raise ValueError("Unsupported JWK kty")
    n = _b64url_to_int(jwk["n"])
    e = _b64url_to_int(jwk["e"])
    numbers = rsa.RSAPublicNumbers(e, n)
    return numbers.public_key()


async def _get_jwks() -> Dict[str, Any]:
    now = time.time()
    cached = _JWKS_CACHE.get("jwks")
    fetched_at = float(_JWKS_CACHE.get("fetched_at", 0.0))
    if cached is not None and (now - fetched_at) < _JWKS_TTL_SECONDS:
        return cached

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(JWKS_URL)
        resp.raise_for_status()
        jwks = resp.json()

    _JWKS_CACHE["jwks"] = jwks
    _JWKS_CACHE["fetched_at"] = now
    return jwks


async def decode_token(token: str) -> Optional[TokenPayload]:
    """Decode and validate a JWT token using JWKS (RS256)."""
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            return None

        jwks = await _get_jwks()
        keys = jwks.get("keys", [])
        jwk = next((k for k in keys if k.get("kid") == kid), None)
        if jwk is None:
            # Force refresh once in case of rotation
            _JWKS_CACHE["jwks"] = None
            jwks = await _get_jwks()
            keys = jwks.get("keys", [])
            jwk = next((k for k in keys if k.get("kid") == kid), None)
            if jwk is None:
                return None

        public_key = _rsa_public_key_from_jwk(jwk)
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        return None
    except Exception:
        return None


async def verify_token(token: str) -> Optional[str]:
    """Verify a JWT access token and return the user_id if valid."""
    payload = await decode_token(token)
    if payload is None or payload.type != "access":
        return None
    return payload.sub


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """Dependency to get current authenticated user from JWT."""
    token = credentials.credentials
    payload = await decode_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return payload


async def get_user_id(
    payload: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UUID:
    """Dependency to get current user's UUID.

    The API service maintains its own database for characters/chats/messages.
    Since authentication is handled by an external auth service, users may not
    exist in the API DB yet. We upsert the user row lazily to satisfy FK
    constraints (e.g., characters.user_id -> users.id).
    """
    user_id = UUID(payload.sub)

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return user_id

    email = payload.email or f"{user_id}@external-auth.local"
    session.add(
        User(
            id=user_id,
            email=email,
            # Password is managed by the auth service; keep a non-null placeholder.
            password_hash="external-auth",
            email_verified=True,
        )
    )

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        # In case of a race (user inserted concurrently), proceed.
    return user_id
