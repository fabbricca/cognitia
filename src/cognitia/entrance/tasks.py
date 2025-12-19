"""Celery background tasks for Cognitia Entrance."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from celery import Task

from .celery_app import celery_app
from .database import async_session_maker
from .email_service import email_service
from .repositories import (
    UserRepository,
    EmailVerificationRepository,
    PasswordResetRepository,
    SubscriptionRepository,
)

logger = logging.getLogger(__name__)


# Custom task base class to handle async operations
class AsyncTask(Task):
    """Base task class that supports async operations."""

    def __call__(self, *args, **kwargs):
        """Override call to run async functions in event loop."""
        result = self.run(*args, **kwargs)
        if asyncio.iscoroutine(result):
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(result)
        return result


# ============================================================================
# Email Tasks
# ============================================================================

@celery_app.task(base=AsyncTask, bind=True, max_retries=3)
async def send_verification_email(
    self,
    user_email: str,
    user_name: str,
    verification_token: str
) -> bool:
    """
    Send email verification link to user.

    Args:
        user_email: User's email address
        user_name: User's name for personalization
        verification_token: Verification token

    Returns:
        True if email sent successfully
    """
    try:
        logger.info(f"Sending verification email to {user_email}")

        success = await email_service.send_verification_email(
            to_email=user_email,
            user_name=user_name or "there",
            verification_token=verification_token
        )

        if success:
            logger.info(f"Verification email sent successfully to {user_email}")
            return True
        else:
            logger.warning(f"Failed to send verification email to {user_email}")
            # Retry with exponential backoff
            raise self.retry(countdown=60 * (2 ** self.request.retries))

    except Exception as exc:
        logger.error(f"Error sending verification email to {user_email}: {exc}")
        # Retry up to 3 times with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery_app.task(base=AsyncTask, bind=True, max_retries=3)
async def send_password_reset_email(
    self,
    user_email: str,
    user_name: str,
    reset_token: str
) -> bool:
    """
    Send password reset link to user.

    Args:
        user_email: User's email address
        user_name: User's name for personalization
        reset_token: Password reset token

    Returns:
        True if email sent successfully
    """
    try:
        logger.info(f"Sending password reset email to {user_email}")

        success = await email_service.send_password_reset_email(
            to_email=user_email,
            user_name=user_name or "there",
            reset_token=reset_token
        )

        if success:
            logger.info(f"Password reset email sent successfully to {user_email}")
            return True
        else:
            logger.warning(f"Failed to send password reset email to {user_email}")
            raise self.retry(countdown=60 * (2 ** self.request.retries))

    except Exception as exc:
        logger.error(f"Error sending password reset email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ============================================================================
# AI Response Generation Task
# ============================================================================

@celery_app.task(base=AsyncTask, bind=True)
async def generate_ai_response(
    self,
    chat_id: str,
    message_id: str,
    character_id: str,
    user_message: str
) -> Optional[str]:
    """
    Generate AI response for a chat message.

    This is a placeholder for Phase 4. In production, this would:
    1. Load the character's configuration
    2. Get conversation history from the database
    3. Call the Core GPU server for LLM inference
    4. Store the AI response as a new message
    5. Optionally generate TTS audio

    Args:
        chat_id: Chat ID
        message_id: User message ID
        character_id: Character to respond as
        user_message: User's message content

    Returns:
        AI response text (or None if failed)
    """
    try:
        logger.info(f"Generating AI response for chat {chat_id}, character {character_id}")

        # TODO: Implement actual AI generation in future phases
        # For now, this is a placeholder that logs the request

        # In production, you would:
        # 1. Query character and chat from database
        # 2. Build conversation context
        # 3. Call Core server: httpx.post(f"{CORE_URL}/generate", json={...})
        # 4. Save AI response to database
        # 5. Optionally generate and save audio
        # 6. Notify connected WebSocket clients

        logger.info(f"AI response generation queued for chat {chat_id}")
        logger.info(f"User message: {user_message[:100]}...")

        return None  # Placeholder

    except Exception as exc:
        logger.error(f"Error generating AI response for chat {chat_id}: {exc}")
        raise


# ============================================================================
# Cleanup Tasks
# ============================================================================

@celery_app.task(base=AsyncTask)
async def cleanup_expired_tokens() -> dict:
    """
    Clean up expired email verification and password reset tokens.

    Runs hourly to keep the database clean.

    Returns:
        Dict with counts of deleted tokens
    """
    try:
        logger.info("Starting token cleanup task")

        async with async_session_maker() as session:
            from .database import EmailVerification, PasswordReset

            email_verif_repo = EmailVerificationRepository(EmailVerification, session)
            password_reset_repo = PasswordResetRepository(PasswordReset, session)

            # Delete expired email verifications
            email_deleted = await email_verif_repo.delete_expired()

            # Delete expired password resets
            password_deleted = await password_reset_repo.delete_expired()

            await session.commit()

        logger.info(f"Cleanup complete: {email_deleted} email verifications, "
                   f"{password_deleted} password resets deleted")

        return {
            "email_verifications_deleted": email_deleted,
            "password_resets_deleted": password_deleted,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as exc:
        logger.error(f"Error in token cleanup task: {exc}")
        raise


# ============================================================================
# Metrics Aggregation Tasks
# ============================================================================

@celery_app.task(base=AsyncTask)
async def aggregate_daily_metrics() -> dict:
    """
    Aggregate daily usage metrics for reporting.

    Runs daily at midnight to calculate:
    - Total messages sent
    - Total audio minutes generated
    - Active users
    - Popular characters

    Returns:
        Dict with aggregated metrics
    """
    try:
        logger.info("Starting daily metrics aggregation")

        async with async_session_maker() as session:
            from .database import Message, User, Character
            from sqlalchemy import select, func, and_

            # Get yesterday's date range
            yesterday = datetime.utcnow().date() - timedelta(days=1)
            start_time = datetime.combine(yesterday, datetime.min.time())
            end_time = datetime.combine(yesterday, datetime.max.time())

            # Count messages
            result = await session.execute(
                select(func.count(Message.id)).where(
                    and_(
                        Message.created_at >= start_time,
                        Message.created_at <= end_time
                    )
                )
            )
            total_messages = result.scalar_one()

            # Count active users (users who sent messages)
            result = await session.execute(
                select(func.count(func.distinct(Message.chat_id))).where(
                    and_(
                        Message.created_at >= start_time,
                        Message.created_at <= end_time
                    )
                )
            )
            active_chats = result.scalar_one()

            # Count total users
            result = await session.execute(select(func.count(User.id)))
            total_users = result.scalar_one()

            # Count total characters
            result = await session.execute(select(func.count(Character.id)))
            total_characters = result.scalar_one()

            metrics = {
                "date": yesterday.isoformat(),
                "total_messages": total_messages,
                "active_chats": active_chats,
                "total_users": total_users,
                "total_characters": total_characters,
                "timestamp": datetime.utcnow().isoformat()
            }

        logger.info(f"Daily metrics aggregated: {metrics}")
        return metrics

    except Exception as exc:
        logger.error(f"Error in daily metrics aggregation: {exc}")
        raise


# ============================================================================
# Subscription Management Tasks
# ============================================================================

@celery_app.task(base=AsyncTask)
async def check_expiring_subscriptions() -> dict:
    """
    Check for subscriptions expiring soon and send notifications.

    Runs daily to notify users about:
    - Subscriptions expiring in 7 days
    - Subscriptions expiring in 3 days
    - Subscriptions expiring in 1 day

    Returns:
        Dict with notification counts
    """
    try:
        logger.info("Checking for expiring subscriptions")

        async with async_session_maker() as session:
            from .database import UserSubscription, User

            subscription_repo = SubscriptionRepository(UserSubscription, session)
            user_repo = UserRepository(User, session)

            # Get subscriptions expiring in the next 7 days
            expiring_soon = await subscription_repo.get_expiring_soon(days=7)

            notifications_sent = 0
            for subscription in expiring_soon:
                user = await user_repo.get(subscription.user_id)
                if not user:
                    continue

                days_until_expiry = (subscription.current_period_end - datetime.utcnow()).days

                if days_until_expiry in [7, 3, 1]:
                    # TODO: Send expiry warning email
                    logger.info(f"Subscription {subscription.id} expires in {days_until_expiry} days "
                              f"for user {user.email}")
                    notifications_sent += 1

        logger.info(f"Expiry check complete: {notifications_sent} notifications sent")

        return {
            "subscriptions_checked": len(expiring_soon),
            "notifications_sent": notifications_sent,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as exc:
        logger.error(f"Error checking expiring subscriptions: {exc}")
        raise


# ============================================================================
# Helper function to run async tasks from sync context
# ============================================================================

def run_async_task(coro):
    """Helper to run async coroutines in Celery tasks."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # Already in async context
        return coro
    else:
        # Need to run in new loop
        return asyncio.run(coro)


# ============================================================================
# Relationship Decay Task
# ============================================================================

@celery_app.task(base=AsyncTask)
async def decay_inactive_relationships() -> dict:
    """
    Apply trust decay to relationships inactive for 7+ days.

    Runs daily to simulate natural relationship drift when
    users don't interact with characters regularly.

    Decay formula:
    - No decay for first 7 days of inactivity
    - After 7 days: -1 trust per day
    - After 30 days: -2 trust per day
    - Sentiment decays toward 0 (neutral) at 20% rate

    Returns:
        Dict with counts of relationships decayed
    """
    try:
        logger.info("Starting relationship decay task")

        async with async_session_maker() as session:
            from datetime import datetime, timedelta
            from sqlalchemy import select
            from .database import Relationship
            from .memory_service import get_stage_for_trust

            now = datetime.utcnow()
            seven_days_ago = now - timedelta(days=7)

            # Get all relationships inactive for 7+ days
            stmt = select(Relationship).where(
                Relationship.last_conversation < seven_days_ago
            )
            result = await session.execute(stmt)
            inactive_relationships = result.scalars().all()

            decay_count = 0
            for rel in inactive_relationships:
                if not rel.last_conversation:
                    continue

                days_inactive = (now - rel.last_conversation).days

                # Skip if less than 7 days
                if days_inactive < 7:
                    continue

                # Calculate trust decay
                if days_inactive >= 30:
                    trust_decay = 2  # -2 per day after 30 days
                else:
                    trust_decay = 1  # -1 per day after 7 days

                # Apply decay (but don't go below 0)
                old_trust = rel.trust_level
                rel.trust_level = max(0, rel.trust_level - trust_decay)

                # Sentiment decays toward neutral (0)
                old_sentiment = rel.sentiment_score
                if rel.sentiment_score > 0:
                    # Positive sentiment decays toward 0
                    sentiment_decay = max(1, int(rel.sentiment_score * 0.2))
                    rel.sentiment_score = max(0, rel.sentiment_score - sentiment_decay)
                elif rel.sentiment_score < 0:
                    # Negative sentiment also decays toward 0
                    sentiment_recovery = max(1, int(abs(rel.sentiment_score) * 0.2))
                    rel.sentiment_score = min(0, rel.sentiment_score + sentiment_recovery)

                # Update stage if trust changed enough
                new_stage = get_stage_for_trust(rel.trust_level)
                if new_stage != rel.stage:
                    logger.info(
                        f"Relationship {rel.id} decayed from {rel.stage} to {new_stage} "
                        f"after {days_inactive} days inactive"
                    )
                    rel.stage = new_stage

                rel.updated_at = now
                decay_count += 1

                logger.debug(
                    f"Decayed relationship {rel.id}: "
                    f"trust {old_trust} -> {rel.trust_level}, "
                    f"sentiment {old_sentiment} -> {rel.sentiment_score} "
                    f"({days_inactive} days inactive)"
                )

            await session.commit()

        logger.info(f"Relationship decay complete: {decay_count} relationships decayed")

        return {
            "relationships_decayed": decay_count,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as exc:
        logger.error(f"Error in relationship decay task: {exc}")
        raise
