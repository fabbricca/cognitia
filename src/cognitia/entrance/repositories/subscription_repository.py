"""Subscription repository with billing queries."""

from typing import Optional, List
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, and_

from .base import BaseRepository
from ..database import UserSubscription, SubscriptionPlan


class SubscriptionRepository(BaseRepository[UserSubscription]):
    """Repository for Subscription operations."""

    async def get_by_user(self, user_id: UUID) -> Optional[UserSubscription]:
        """Get active subscription for user."""
        result = await self.session.execute(
            select(UserSubscription).where(
                and_(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status.in_(["active", "trialing"])
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_stripe_subscription_id(
        self,
        stripe_subscription_id: str
    ) -> Optional[UserSubscription]:
        """Get subscription by Stripe subscription ID."""
        result = await self.session.execute(
            select(UserSubscription).where(
                UserSubscription.stripe_subscription_id == stripe_subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def get_expiring_soon(
        self,
        days: int = 7
    ) -> List[UserSubscription]:
        """Get subscriptions expiring in N days."""
        from datetime import timedelta
        expiry_date = datetime.utcnow() + timedelta(days=days)

        result = await self.session.execute(
            select(UserSubscription).where(
                and_(
                    UserSubscription.status == "active",
                    UserSubscription.current_period_end <= expiry_date,
                    UserSubscription.cancel_at_period_end == False
                )
            )
        )
        return list(result.scalars().all())

    async def get_cancelled_subscriptions(self) -> List[UserSubscription]:
        """Get all cancelled subscriptions."""
        result = await self.session.execute(
            select(UserSubscription).where(
                UserSubscription.cancel_at_period_end == True
            )
        )
        return list(result.scalars().all())


class SubscriptionPlanRepository(BaseRepository[SubscriptionPlan]):
    """Repository for SubscriptionPlan operations."""

    async def get_by_name(self, name: str) -> Optional[SubscriptionPlan]:
        """Get plan by unique name."""
        result = await self.session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.name == name)
        )
        return result.scalar_one_or_none()

    async def get_active_plans(self) -> List[SubscriptionPlan]:
        """Get all active plans."""
        result = await self.session.execute(
            select(SubscriptionPlan)
            .where(SubscriptionPlan.is_active == True)
            .order_by(SubscriptionPlan.sort_order)
        )
        return list(result.scalars().all())
