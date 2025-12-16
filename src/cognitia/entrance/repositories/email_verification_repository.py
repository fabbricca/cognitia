"""Email verification token repository."""

from typing import Optional
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, and_

from .base import BaseRepository
from ..database import EmailVerification


class EmailVerificationRepository(BaseRepository[EmailVerification]):
    """Repository for EmailVerification operations."""

    async def get_by_token(self, token: str) -> Optional[EmailVerification]:
        """Get verification by token."""
        result = await self.session.execute(
            select(EmailVerification).where(EmailVerification.token == token)
        )
        return result.scalar_one_or_none()

    async def get_by_user(self, user_id: UUID) -> Optional[EmailVerification]:
        """Get pending verification for user."""
        result = await self.session.execute(
            select(EmailVerification).where(EmailVerification.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def delete_expired(self) -> int:
        """Delete expired verification tokens. Returns count deleted."""
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(EmailVerification).where(
                EmailVerification.expires_at < datetime.utcnow()
            )
        )
        return result.rowcount

    async def delete_by_user(self, user_id: UUID) -> bool:
        """Delete verification token for user."""
        verification = await self.get_by_user(user_id)
        if not verification:
            return False

        await self.session.delete(verification)
        await self.session.flush()
        return True
