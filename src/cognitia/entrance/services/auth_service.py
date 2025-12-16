"""Authentication service with email verification."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID

from ..repositories.user_repository import UserRepository
from ..repositories.email_verification_repository import EmailVerificationRepository
from ..repositories.password_reset_repository import PasswordResetRepository
from ..core.security import hash_password, verify_password, create_jwt_token
from ..core.exceptions import (
    InvalidCredentialsError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidTokenError,
)
from ..schemas.auth import TokenResponse
from ..database import User


class AuthService:
    """Authentication service with email verification."""

    def __init__(
        self,
        user_repo: UserRepository,
        email_verification_repo: EmailVerificationRepository,
        password_reset_repo: PasswordResetRepository,
    ):
        self.user_repo = user_repo
        self.email_verification_repo = email_verification_repo
        self.password_reset_repo = password_reset_repo

    async def register(
        self,
        email: str,
        password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Tuple[User, str]:
        """
        Register new user and generate verification token.

        Returns: (user, verification_token)
        """
        # Check if email exists
        if await self.user_repo.email_exists(email):
            raise EmailAlreadyExistsError(f"Email {email} already registered")

        # Create user (email_verified=false by default)
        user = await self.user_repo.create(
            email=email,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role="user",
            email_verified=False,
        )

        # Generate verification token (24h expiry)
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=24)

        await self.email_verification_repo.create(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
        )

        # TODO: Send verification email via Celery task (Phase 4)
        # send_verification_email.delay(email=user.email, token=token)

        return user, token

    async def verify_email(self, token: str) -> User:
        """Verify user's email with token."""
        verification = await self.email_verification_repo.get_by_token(token)

        if not verification:
            raise InvalidTokenError("Invalid verification token")

        if verification.expires_at < datetime.utcnow():
            raise InvalidTokenError("Verification token expired")

        # Mark user as verified
        user = await self.user_repo.update(
            verification.user_id,
            email_verified=True,
        )

        # Delete verification token
        await self.email_verification_repo.delete(verification.id)

        return user

    async def login(
        self,
        email: str,
        password: str,
        require_verification: bool = True,
    ) -> TokenResponse:
        """Login and return JWT tokens."""
        user = await self.user_repo.get_by_email(email)

        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")

        if require_verification and not user.email_verified:
            raise EmailNotVerifiedError(
                "Please verify your email before logging in"
            )

        # Update last active
        await self.user_repo.update(
            user.id,
            last_active_at=datetime.utcnow(),
        )

        # Generate tokens
        access_token = create_jwt_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            token_type="access",
            expires_minutes=60,
        )
        refresh_token = create_jwt_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            token_type="refresh",
            expires_days=30,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
        )

    async def request_password_reset(self, email: str) -> Optional[str]:
        """
        Send password reset email.

        Returns: reset_token if user exists, None otherwise
        """
        user = await self.user_repo.get_by_email(email)
        if not user:
            # Don't reveal if email exists
            return None

        # Generate reset token (1h expiry)
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)

        await self.password_reset_repo.create(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
            used=False,
        )

        # Queue password reset email task (async background job)
        from ..tasks import send_password_reset_email as send_reset_task
        send_reset_task.delay(
            user_email=user.email,
            user_name=user.first_name or user.email.split('@')[0],
            reset_token=token
        )

        return token

    async def reset_password(self, token: str, new_password: str) -> User:
        """Reset password using token."""
        reset = await self.password_reset_repo.get_by_token(token)

        if not reset:
            raise InvalidTokenError("Invalid reset token")

        if reset.expires_at < datetime.utcnow():
            raise InvalidTokenError("Reset token expired")

        # Update password
        user = await self.user_repo.update(
            reset.user_id,
            password_hash=hash_password(new_password),
        )

        # Mark token as used
        await self.password_reset_repo.mark_as_used(token)

        return user

    async def refresh_access_token(self, refresh_token: str) -> str:
        """Generate new access token from refresh token."""
        from ..core.security import verify_jwt_token

        payload = verify_jwt_token(refresh_token, expected_type="refresh")
        if not payload:
            raise InvalidTokenError("Invalid refresh token")

        # Verify user still exists
        user = await self.user_repo.get(UUID(payload.sub))
        if not user:
            raise InvalidTokenError("User not found")

        # Generate new access token
        return create_jwt_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            token_type="access",
            expires_minutes=60,
        )
