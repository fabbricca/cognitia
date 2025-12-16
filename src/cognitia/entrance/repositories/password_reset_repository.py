"""Password reset token repository."""

from typing import Optional
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, and_

from .base import BaseRepository
from ..database import PasswordReset


class PasswordResetRepository(BaseRepository[PasswordReset]):
    """Repository for PasswordReset operations."""

    async def get_by_token(self, token: str) -> Optional[PasswordReset]:
        """Get password reset by token."""
        result = await self.session.execute(
            select(PasswordReset).where(
                and_(
                    PasswordReset.token == token,
                    PasswordReset.used == False
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        user_id: UUID,
        only_unused: bool = True
    ) -> Optional[PasswordReset]:
        """Get latest password reset for user."""
        query = select(PasswordReset).where(PasswordReset.user_id == user_id)

        if only_unused:
            query = query.where(PasswordReset.used == False)

        query = query.order_by(PasswordReset.created_at.desc())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def mark_as_used(self, token: str) -> bool:
        """Mark password reset token as used."""
        reset = await self.get_by_token(token)
        if not reset:
            return False

        reset.used = True
        await self.session.flush()
        return True

    async def delete_expired(self) -> int:
        """Delete expired password reset tokens. Returns count deleted."""
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(PasswordReset).where(
                PasswordReset.expires_at < datetime.utcnow()
            )
        )
        return result.rowcount

    async def delete_by_user(self, user_id: UUID) -> int:
        """Delete all password reset tokens for user. Returns count deleted."""
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(PasswordReset).where(PasswordReset.user_id == user_id)
        )
        return result.rowcount
