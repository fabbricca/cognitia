"""User repository with authentication queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select

from .base import BaseRepository
from ..database import User


class UserRepository(BaseRepository[User]):
    """Repository for User operations."""

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email address."""
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        """Check if email is already registered."""
        result = await self.session.execute(
            select(User.id).where(User.email == email)
        )
        return result.scalar_one_or_none() is not None

    async def get_by_referral_code(self, referral_code: str) -> Optional[User]:
        """Get user by referral code."""
        result = await self.session.execute(
            select(User).where(User.referral_code == referral_code)
        )
        return result.scalar_one_or_none()

    async def get_admins(self) -> list[User]:
        """Get all admin users."""
        result = await self.session.execute(
            select(User).where(User.role == "admin")
        )
        return list(result.scalars().all())

    async def get_unverified_users(self) -> list[User]:
        """Get all users with unverified emails."""
        result = await self.session.execute(
            select(User).where(User.email_verified == False)
        )
        return list(result.scalars().all())
