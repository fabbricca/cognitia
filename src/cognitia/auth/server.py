import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cognitia.api.auth import hash_password, verify_password
from cognitia.api.database import User, get_session

from .config import (
    ACCESS_TOKEN_TTL_MINUTES,
    AUDIENCE,
    ISSUER,
    KEY_ID,
    PRIVATE_KEY_PATH,
    PUBLIC_KEY_PATH,
    REFRESH_TOKEN_TTL_DAYS,
)
from .jwks import JwksKey, load_rsa_private_key_pem, load_rsa_public_key_pem
from .schemas import HealthResponse, TokenRefresh, TokenResponse, UserCreate, UserLogin


ALGORITHM = "RS256"


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_token(*, token_type: str, user_id: UUID, email: str, ttl: timedelta, private_key_pem: bytes) -> str:
    issued_at = _now()
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "email": email,
        "type": token_type,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + ttl).timestamp()),
    }
    headers = {"kid": KEY_ID, "typ": "JWT"}
    return jwt.encode(payload, private_key_pem, algorithm=ALGORITHM, headers=headers)


def create_app() -> FastAPI:
    app = FastAPI(title="Cognitia Auth", version="1.0.0")

    private_key_pem = _read_file(PRIVATE_KEY_PATH)
    public_key_pem = _read_file(PUBLIC_KEY_PATH)

    private_key = load_rsa_private_key_pem(private_key_pem)
    public_key = load_rsa_public_key_pem(public_key_pem)
    jwks_key = JwksKey(kid=KEY_ID, public_key=public_key)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/.well-known/jwks.json")
    async def jwks():
        return {"keys": [jwks_key.as_jwk()]}

    @app.post("/api/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
    async def register(data: UserCreate, session: AsyncSession = Depends(get_session)) -> TokenResponse:
        result = await session.execute(select(User).where(User.email == data.email))
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

        user = User(email=data.email, password_hash=hash_password(data.password))
        session.add(user)
        await session.commit()
        await session.refresh(user)

        access = _make_token(
            token_type="access",
            user_id=user.id,
            email=user.email,
            ttl=timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
            private_key_pem=private_key_pem,
        )
        refresh = _make_token(
            token_type="refresh",
            user_id=user.id,
            email=user.email,
            ttl=timedelta(days=REFRESH_TOKEN_TTL_DAYS),
            private_key_pem=private_key_pem,
        )
        return TokenResponse(access_token=access, refresh_token=refresh)

    @app.post("/api/auth/login", response_model=TokenResponse)
    async def login(data: UserLogin, session: AsyncSession = Depends(get_session)) -> TokenResponse:
        result = await session.execute(select(User).where(User.email == data.email))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        access = _make_token(
            token_type="access",
            user_id=user.id,
            email=user.email,
            ttl=timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
            private_key_pem=private_key_pem,
        )
        refresh = _make_token(
            token_type="refresh",
            user_id=user.id,
            email=user.email,
            ttl=timedelta(days=REFRESH_TOKEN_TTL_DAYS),
            private_key_pem=private_key_pem,
        )
        return TokenResponse(access_token=access, refresh_token=refresh)

    @app.post("/api/auth/refresh", response_model=TokenResponse)
    async def refresh_token(data: TokenRefresh, session: AsyncSession = Depends(get_session)) -> TokenResponse:
        try:
            payload = jwt.decode(
                data.refresh_token,
                public_key_pem,
                algorithms=[ALGORITHM],
                audience=AUDIENCE,
                issuer=ISSUER,
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired refresh token")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

        user_id = UUID(payload.get("sub"))
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        access = _make_token(
            token_type="access",
            user_id=user.id,
            email=user.email,
            ttl=timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
            private_key_pem=private_key_pem,
        )
        refresh = _make_token(
            token_type="refresh",
            user_id=user.id,
            email=user.email,
            ttl=timedelta(days=REFRESH_TOKEN_TTL_DAYS),
            private_key_pem=private_key_pem,
        )
        return TokenResponse(access_token=access, refresh_token=refresh)

    return app


app = create_app()
