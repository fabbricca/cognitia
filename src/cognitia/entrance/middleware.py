"""Middleware for subscription enforcement and rate limiting."""

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, and_
from starlette.middleware.base import BaseHTTPMiddleware

from .database import (
    async_session_maker,
    UserSubscription,
    SubscriptionPlan,
    DailyUsageCache,
    User,
)
from .email_service import email_service

logger = logging.getLogger(__name__)

# Track sent warnings to avoid spam (resets daily)
_sent_warnings = {}  # {(user_id, date, resource, threshold): True}


class SubscriptionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce subscription limits and rate limiting.

    This middleware runs BEFORE route handlers and checks:
    1. Rate limits (messages, audio generation)
    2. Feature access based on subscription tier
    3. Character creation limits
    """

    # Routes that bypass all subscription checks
    PUBLIC_ROUTES = {
        "/health",
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/refresh",
        "/api/subscription/plans",
    }

    # Static file patterns that bypass checks
    STATIC_PATTERNS = ("/", "/css/", "/js/", "/avatars/", "/fonts/", "/images/")

    async def dispatch(self, request: Request, call_next):
        """Process each request through subscription checks."""

        # Skip middleware for public routes
        if request.url.path in self.PUBLIC_ROUTES:
            return await call_next(request)

        # Skip for static files
        if any(request.url.path.startswith(pattern) for pattern in self.STATIC_PATTERNS):
            return await call_next(request)

        # Get user ID from request state (set by auth dependency)
        user_id = getattr(request.state, "user_id", None)

        # If no user, skip checks (unauthenticated routes)
        if not user_id:
            return await call_next(request)

        try:
            # Check rate limits for specific endpoints
            if request.method == "POST":
                if "/messages" in request.url.path:
                    await self._check_message_limit(user_id)
                elif "/characters" in request.url.path and not any(
                    seg for seg in request.url.path.split("/") if len(seg) == 36
                ):  # Creating new character (no UUID in path)
                    await self._check_character_limit(user_id)

            # Process request
            response = await call_next(request)
            return response

        except HTTPException as e:
            # Convert HTTPException to JSONResponse for better error handling
            return JSONResponse(
                status_code=e.status_code,
                content=e.detail if isinstance(e.detail, dict) else {"error": e.detail}
            )
        except Exception as e:
            logger.error(f"Subscription middleware error: {e}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Internal server error"}
            )

    async def _check_message_limit(self, user_id: UUID):
        """Check if user has exceeded daily message limit."""
        async with async_session_maker() as session:
            # Get user's subscription and plan
            result = await session.execute(
                select(UserSubscription, SubscriptionPlan)
                .join(SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id)
                .where(UserSubscription.user_id == user_id)
            )
            row = result.first()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "no_subscription",
                        "message": "No active subscription found. Please subscribe to continue.",
                        "upgrade_url": "/subscription"
                    }
                )

            subscription, plan = row

            # Check subscription status
            if subscription.status != "active":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "subscription_inactive",
                        "message": f"Your subscription is {subscription.status}",
                        "status": subscription.status
                    }
                )

            # Get today's usage
            today = date.today()
            usage_result = await session.execute(
                select(DailyUsageCache).where(
                    and_(
                        DailyUsageCache.user_id == user_id,
                        DailyUsageCache.date == today
                    )
                )
            )
            usage = usage_result.scalar_one_or_none()

            current_count = usage.messages_count if usage else 0

            # Calculate percentage
            percentage = (current_count / plan.max_messages_per_day * 100) if plan.max_messages_per_day > 0 else 0

            # Send usage warnings at 80%, 90%, and 100%
            await self._send_usage_warning_if_needed(
                session, user_id, "messages", current_count,
                plan.max_messages_per_day, percentage, plan.name, today
            )

            # Check limit
            if current_count >= plan.max_messages_per_day:
                reset_time = datetime.combine(today + timedelta(days=1), datetime.min.time())
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "daily_limit_exceeded",
                        "message": f"You've reached your daily limit of {plan.max_messages_per_day} messages.",
                        "limit": plan.max_messages_per_day,
                        "used": current_count,
                        "reset_at": reset_time.isoformat(),
                        "current_plan": plan.name,
                        "upgrade_url": "/subscription/plans"
                    }
                )

            logger.debug(f"User {user_id} message check: {current_count}/{plan.max_messages_per_day}")

    async def _check_audio_limit(self, user_id: UUID) -> None:
        """Check if user has exceeded daily audio generation limit."""
        async with async_session_maker() as session:
            # Get user's subscription and plan
            result = await session.execute(
                select(UserSubscription, SubscriptionPlan)
                .join(SubscriptionPlan)
                .where(UserSubscription.user_id == user_id)
            )
            row = result.first()

            if not row:
                return  # No subscription, skip check

            subscription, plan = row

            # Get today's usage
            today = date.today()
            usage_result = await session.execute(
                select(DailyUsageCache).where(
                    and_(
                        DailyUsageCache.user_id == user_id,
                        DailyUsageCache.date == today
                    )
                )
            )
            usage = usage_result.scalar_one_or_none()

            current_minutes = float(usage.audio_minutes) if usage else 0.0

            # Check limit
            if current_minutes >= plan.max_audio_minutes_per_day:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "audio_limit_exceeded",
                        "message": f"You've reached your daily audio limit of {plan.max_audio_minutes_per_day} minutes.",
                        "limit": plan.max_audio_minutes_per_day,
                        "used": current_minutes,
                        "current_plan": plan.name,
                        "upgrade_url": "/subscription/plans"
                    }
                )

    async def _check_character_limit(self, user_id: UUID) -> None:
        """Check if user can create more characters."""
        async with async_session_maker() as session:
            # Get user's subscription and plan
            result = await session.execute(
                select(UserSubscription, SubscriptionPlan)
                .join(SubscriptionPlan)
                .where(UserSubscription.user_id == user_id)
            )
            row = result.first()

            if not row:
                return  # No subscription check

            subscription, plan = row

            # Count user's existing characters
            from .database import Character
            count_result = await session.execute(
                select(Character).where(Character.user_id == user_id)
            )
            character_count = len(count_result.scalars().all())

            # Check limit
            if character_count >= plan.max_characters:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "character_limit_exceeded",
                        "message": f"You've reached your character limit of {plan.max_characters}.",
                        "limit": plan.max_characters,
                        "used": character_count,
                        "current_plan": plan.name,
                        "upgrade_url": "/subscription/plans"
                    }
                )

    async def _send_usage_warning_if_needed(
        self,
        session,
        user_id: UUID,
        resource_type: str,
        used: int,
        limit: int,
        percentage: float,
        plan_name: str,
        today: date
    ) -> None:
        """Send email warning if usage threshold reached."""
        # Determine which threshold we've crossed
        threshold = None
        if percentage >= 100:
            threshold = 100
        elif percentage >= 90:
            threshold = 90
        elif percentage >= 80:
            threshold = 80
        else:
            return  # No warning needed

        # Check if we've already sent this warning today
        warning_key = (str(user_id), str(today), resource_type, threshold)
        if warning_key in _sent_warnings:
            return  # Already sent

        # Get user email
        user_result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            return

        # Send warning email (non-blocking)
        try:
            import asyncio
            asyncio.create_task(
                email_service.send_usage_warning(
                    to_email=user.email,
                    user_name=user.email.split('@')[0],
                    resource_type=resource_type,
                    used=used,
                    limit=limit,
                    percentage=percentage,
                    plan_name=plan_name
                )
            )
            # Mark as sent
            _sent_warnings[warning_key] = True
            logger.info(f"Sent {threshold}% usage warning for {resource_type} to {user.email}")
        except Exception as e:
            logger.error(f"Failed to send usage warning email: {e}", exc_info=True)

    async def check_feature_access(self, user_id: UUID, feature: str) -> bool:
        """
        Check if user has access to a specific feature.

        Args:
            user_id: User's UUID
            feature: Feature name ('custom_voice', 'phone_calls', 'api_access', etc.)

        Returns:
            bool: True if user has access

        Raises:
            HTTPException: If user doesn't have access
        """
        async with async_session_maker() as session:
            result = await session.execute(
                select(UserSubscription, SubscriptionPlan)
                .join(SubscriptionPlan)
                .where(UserSubscription.user_id == user_id)
            )
            row = result.first()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "no_subscription",
                        "message": "Subscription required"
                    }
                )

            subscription, plan = row

            # Map feature names to plan attributes
            feature_map = {
                'custom_voice': plan.can_use_custom_voices,
                'phone_calls': plan.can_use_phone_calls,
                'premium_models': plan.can_access_premium_models,
                'export_conversations': plan.can_export_conversations,
                'api_access': plan.api_access,
                'webhooks': plan.webhook_support,
                'priority_processing': plan.priority_processing,
            }

            has_access = feature_map.get(feature, False)

            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "feature_not_available",
                        "message": f"Your plan doesn't include {feature.replace('_', ' ')}.",
                        "feature": feature,
                        "upgrade_required": True,
                        "current_plan": plan.name,
                        "upgrade_url": "/subscription/plans"
                    }
                )

            return True


# Singleton instance
subscription_middleware = SubscriptionMiddleware(app=None)  # app will be set when added to FastAPI
