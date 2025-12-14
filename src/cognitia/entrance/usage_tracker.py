"""Usage tracking for billing and analytics."""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Dict
from uuid import UUID

from sqlalchemy import text, select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .database import (
    async_session_maker,
    DailyUsageCache,
    UsageRecord,
    SubscriptionPlan,
    UserSubscription,
)

logger = logging.getLogger(__name__)


class UsageTracker:
    """
    Track and record usage for billing, analytics, and rate limiting.

    This class provides methods to:
    - Record message sends
    - Record audio generation
    - Record voice cloning
    - Get usage statistics
    """

    async def record_message(
        self,
        user_id: UUID,
        chat_id: UUID,
        character_id: Optional[UUID] = None,
        tokens: int = 0
    ) -> None:
        """
        Record a message sent by user.

        Args:
            user_id: User's UUID
            chat_id: Chat UUID
            character_id: Optional character UUID
            tokens: Number of tokens used in LLM generation
        """
        try:
            async with async_session_maker() as session:
                today = date.today()

                # Insert detailed usage record
                usage_record = UsageRecord(
                    user_id=user_id,
                    resource_type="message",
                    quantity=1,
                    tokens_used=tokens if tokens > 0 else None,
                    chat_id=chat_id,
                    character_id=character_id,
                )
                session.add(usage_record)

                # Update daily cache using PostgreSQL UPSERT
                # For SQLite, we need to check first
                existing = await session.execute(
                    select(DailyUsageCache).where(
                        and_(
                            DailyUsageCache.user_id == user_id,
                            DailyUsageCache.date == today
                        )
                    )
                )
                cache = existing.scalar_one_or_none()

                if cache:
                    cache.messages_count += 1
                    cache.total_tokens += tokens
                    cache.updated_at = datetime.utcnow()
                else:
                    cache = DailyUsageCache(
                        user_id=user_id,
                        date=today,
                        messages_count=1,
                        total_tokens=tokens,
                    )
                    session.add(cache)

                await session.commit()
                logger.info(f"Tracked message for user {user_id}: {tokens} tokens")

        except Exception as e:
            logger.error(f"Failed to track message usage: {e}", exc_info=True)
            # Don't raise - usage tracking shouldn't break the app

    async def record_audio(
        self,
        user_id: UUID,
        duration_seconds: float,
        character_id: Optional[UUID] = None,
        chat_id: Optional[UUID] = None,
    ) -> None:
        """
        Record audio generation.

        Args:
            user_id: User's UUID
            duration_seconds: Audio duration in seconds
            character_id: Optional character UUID
            chat_id: Optional chat UUID
        """
        try:
            async with async_session_maker() as session:
                today = date.today()
                minutes = Decimal(str(duration_seconds / 60))

                # Insert detailed usage record
                usage_record = UsageRecord(
                    user_id=user_id,
                    resource_type="audio_generation",
                    quantity=1,
                    audio_duration_seconds=Decimal(str(duration_seconds)),
                    chat_id=chat_id,
                    character_id=character_id,
                )
                session.add(usage_record)

                # Update daily cache
                existing = await session.execute(
                    select(DailyUsageCache).where(
                        and_(
                            DailyUsageCache.user_id == user_id,
                            DailyUsageCache.date == today
                        )
                    )
                )
                cache = existing.scalar_one_or_none()

                if cache:
                    cache.audio_minutes += minutes
                    cache.updated_at = datetime.utcnow()
                else:
                    cache = DailyUsageCache(
                        user_id=user_id,
                        date=today,
                        audio_minutes=minutes,
                        messages_count=0,
                        total_tokens=0,
                    )
                    session.add(cache)

                await session.commit()
                logger.info(f"Tracked audio for user {user_id}: {minutes:.2f} minutes")

        except Exception as e:
            logger.error(f"Failed to track audio usage: {e}", exc_info=True)

    async def record_voice_clone(
        self,
        user_id: UUID,
        character_id: UUID,
        model_size_mb: Optional[float] = None,
    ) -> None:
        """
        Record voice cloning model upload.

        Args:
            user_id: User's UUID
            character_id: Character UUID
            model_size_mb: Size of uploaded model in MB
        """
        try:
            async with async_session_maker() as session:
                usage_record = UsageRecord(
                    user_id=user_id,
                    resource_type="voice_clone",
                    quantity=1,
                    character_id=character_id,
                )
                session.add(usage_record)
                await session.commit()
                logger.info(f"Tracked voice clone for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to track voice clone usage: {e}", exc_info=True)

    async def get_today_usage(self, user_id: UUID) -> Dict:
        """
        Get user's usage for today.

        Args:
            user_id: User's UUID

        Returns:
            Dict with usage statistics
        """
        async with async_session_maker() as session:
            today = date.today()

            result = await session.execute(
                select(DailyUsageCache).where(
                    and_(
                        DailyUsageCache.user_id == user_id,
                        DailyUsageCache.date == today
                    )
                )
            )
            cache = result.scalar_one_or_none()

            if cache:
                return {
                    "messages": cache.messages_count,
                    "audio_minutes": float(cache.audio_minutes),
                    "tokens": cache.total_tokens,
                    "date": today.isoformat(),
                }

            return {
                "messages": 0,
                "audio_minutes": 0.0,
                "tokens": 0,
                "date": today.isoformat(),
            }

    async def get_usage_with_limits(self, user_id: UUID) -> Dict:
        """
        Get today's usage along with subscription limits.

        Args:
            user_id: User's UUID

        Returns:
            Dict with usage, limits, and percentages
        """
        async with async_session_maker() as session:
            # Get subscription and plan
            result = await session.execute(
                select(UserSubscription, SubscriptionPlan)
                .join(SubscriptionPlan)
                .where(UserSubscription.user_id == user_id)
            )
            row = result.first()

            if not row:
                return {
                    "error": "no_subscription",
                    "message": "No active subscription found"
                }

            subscription, plan = row

            # Get today's usage
            usage = await self.get_today_usage(user_id)

            # Calculate percentages
            message_percentage = (usage["messages"] / plan.max_messages_per_day * 100) if plan.max_messages_per_day > 0 else 0
            audio_percentage = (usage["audio_minutes"] / plan.max_audio_minutes_per_day * 100) if plan.max_audio_minutes_per_day > 0 else 0

            return {
                "usage": usage,
                "limits": {
                    "messages": plan.max_messages_per_day,
                    "audio_minutes": plan.max_audio_minutes_per_day,
                    "characters": plan.max_characters,
                },
                "percentage": {
                    "messages": round(message_percentage, 1),
                    "audio": round(audio_percentage, 1),
                },
                "plan": {
                    "name": plan.name,
                    "display_name": plan.display_name,
                },
                "subscription": {
                    "status": subscription.status,
                    "current_period_end": subscription.current_period_end.isoformat(),
                }
            }

    async def get_monthly_usage(self, user_id: UUID, year: int, month: int) -> Dict:
        """
        Get user's usage for a specific month.

        Args:
            user_id: User's UUID
            year: Year
            month: Month (1-12)

        Returns:
            Dict with monthly statistics
        """
        async with async_session_maker() as session:
            # Get all daily usage for the month
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)

            result = await session.execute(
                select(DailyUsageCache).where(
                    and_(
                        DailyUsageCache.user_id == user_id,
                        DailyUsageCache.date >= start_date,
                        DailyUsageCache.date < end_date
                    )
                )
            )
            daily_records = result.scalars().all()

            # Aggregate
            total_messages = sum(r.messages_count for r in daily_records)
            total_audio_minutes = sum(float(r.audio_minutes) for r in daily_records)
            total_tokens = sum(r.total_tokens for r in daily_records)

            return {
                "year": year,
                "month": month,
                "total_messages": total_messages,
                "total_audio_minutes": round(total_audio_minutes, 2),
                "total_tokens": total_tokens,
                "days_active": len(daily_records),
            }


# Global singleton instance
usage_tracker = UsageTracker()
