"""Authentication utilities.

Entrance can run in two modes:
- Legacy/local auth: HS256 tokens issued and verified here.
- External auth service: RS256 tokens verified via JWKS.

In Kubernetes, we route `/api/auth/*` to the dedicated auth service, so Entrance
must be able to validate RS256 access tokens.
"""

import base64
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

import bcrypt
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# External auth (JWKS / RS256)
JWKS_URL = os.getenv("JWKS_URL", "http://cognitia-auth:8000/.well-known/jwks.json")
JWT_ISSUER = os.getenv("JWT_ISSUER", "https://auth.cognitia.iberu.me").rstrip("/")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "cognitia-api")

_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "jwks": None}
_JWKS_TTL_SECONDS = int(os.getenv("JWKS_CACHE_TTL_SECONDS", "300"))

security = HTTPBearer()


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # user_id
    email: Optional[str] = None
    exp: datetime
    type: str  # "access" or "refresh"
    iss: Optional[str] = None
    aud: Optional[str] = None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: UUID, email: str) -> str:
    """Create a JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: UUID, email: str) -> str:
    """Create a JWT refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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


def _get_jwks_sync() -> Dict[str, Any]:
    now = time.time()
    cached = _JWKS_CACHE.get("jwks")
    fetched_at = float(_JWKS_CACHE.get("fetched_at", 0.0))
    if cached is not None and (now - fetched_at) < _JWKS_TTL_SECONDS:
        return cached

    with httpx.Client(timeout=5.0) as client:
        resp = client.get(JWKS_URL)
        resp.raise_for_status()
        jwks = resp.json()

    _JWKS_CACHE["jwks"] = jwks
    _JWKS_CACHE["fetched_at"] = now
    return jwks


def decode_token(token: str) -> Optional[TokenPayload]:
    """Decode and validate a JWT token."""
    # Prefer RS256 (auth service) if the token header suggests it.
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        kid = header.get("kid")
        if alg == "RS256" or kid:
            jwks = _get_jwks_sync()
            keys = jwks.get("keys", [])
            jwk = next((k for k in keys if not kid or k.get("kid") == kid), None)
            if jwk is None:
                # Force refresh once (key rotation)
                _JWKS_CACHE["jwks"] = None
                jwks = _get_jwks_sync()
                keys = jwks.get("keys", [])
                jwk = next((k for k in keys if not kid or k.get("kid") == kid), None)
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
    except Exception:
        # Fall through to HS256 legacy verification
        pass

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def verify_token(token: str) -> Optional[str]:
    """Verify a JWT token and return the user_id if valid."""
    payload = decode_token(token)
    if payload is None or payload.type != "access":
        return None
    return payload.sub


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """Dependency to get current authenticated user from JWT."""
    token = credentials.credentials
    payload = decode_token(token)
    
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


def get_user_id(payload: TokenPayload = Depends(get_current_user)) -> UUID:
    """Dependency to get current user's UUID."""
    return UUID(payload.sub)
