"""Subscription management endpoints."""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .auth import get_current_user, TokenPayload
from .database import (
    SubscriptionPlan,
    UserSubscription,
    Character,
    get_session_dep,
)
from .schemas import (
    SubscriptionPlanResponse,
    UserSubscriptionResponse,
    UsageResponse,
)
from .usage_tracker import usage_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


@router.get("/plans", response_model=List[SubscriptionPlanResponse])
async def get_plans(session=Depends(get_session_dep)):
    """
    Get all available subscription plans.

    This is a public endpoint - no authentication required.
    """
    result = await session.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.sort_order)
    )
    plans = result.scalars().all()

    return [
        SubscriptionPlanResponse(
            id=str(plan.id),
            name=plan.name,
            display_name=plan.display_name,
            price_monthly=float(plan.price_monthly),
            price_yearly=float(plan.price_yearly) if plan.price_yearly else None,
            max_characters=plan.max_characters,
            max_messages_per_day=plan.max_messages_per_day,
            max_audio_minutes_per_day=plan.max_audio_minutes_per_day,
            max_voice_clones=plan.max_voice_clones,
            can_use_custom_voices=plan.can_use_custom_voices,
            can_use_phone_calls=plan.can_use_phone_calls,
            can_access_premium_models=plan.can_access_premium_models,
            can_export_conversations=plan.can_export_conversations,
            priority_processing=plan.priority_processing,
            api_access=plan.api_access,
            webhook_support=plan.webhook_support,
            max_context_messages=plan.max_context_messages,
        )
        for plan in plans
    ]


@router.get("/current", response_model=UserSubscriptionResponse)
async def get_current_subscription(
    current_user: TokenPayload = Depends(get_current_user),
    session=Depends(get_session_dep)
):
    """Get user's current subscription details."""
    user_id = UUID(current_user.sub)

    result = await session.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == user_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found"
        )

    plan = subscription.plan

    # Get character count
    char_result = await session.execute(
        select(Character).where(Character.user_id == user_id)
    )
    character_count = len(char_result.scalars().all())

    return UserSubscriptionResponse(
        id=str(subscription.id),
        user_id=str(subscription.user_id),
        plan_id=str(subscription.plan_id),
        plan_name=plan.name,
        plan_display_name=plan.display_name,
        status=subscription.status,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        # Include limits for convenience
        limits={
            "max_characters": plan.max_characters,
            "max_messages_per_day": plan.max_messages_per_day,
            "max_audio_minutes_per_day": plan.max_audio_minutes_per_day,
            "max_voice_clones": plan.max_voice_clones,
        },
        usage={
            "characters": character_count,
        },
        features={
            "can_use_custom_voices": plan.can_use_custom_voices,
            "can_use_phone_calls": plan.can_use_phone_calls,
            "can_access_premium_models": plan.can_access_premium_models,
            "api_access": plan.api_access,
            "webhook_support": plan.webhook_support,
            "priority_processing": plan.priority_processing,
        }
    )


@router.get("/usage", response_model=UsageResponse)
async def get_usage_stats(
    current_user: TokenPayload = Depends(get_current_user),
):
    """
    Get user's current usage statistics with limits.

    Returns today's usage along with subscription limits and percentages.
    """
    user_id = UUID(current_user.sub)
    usage_data = await usage_tracker.get_usage_with_limits(user_id)

    if "error" in usage_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=usage_data["message"]
        )

    return UsageResponse(**usage_data)


@router.get("/usage/monthly/{year}/{month}")
async def get_monthly_usage(
    year: int,
    month: int,
    current_user: TokenPayload = Depends(get_current_user),
):
    """
    Get user's usage for a specific month.

    Args:
        year: Year (e.g., 2025)
        month: Month (1-12)
    """
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Month must be between 1 and 12"
        )
    user_id = UUID(current_user.sub)
    monthly_data = await usage_tracker.get_monthly_usage(user_id, year, month)
    return monthly_data


@router.post("/cancel")
async def cancel_subscription(
    current_user: TokenPayload = Depends(get_current_user),
    session=Depends(get_session_dep)
):
    """
    Cancel subscription at end of billing period.

    The subscription will remain active until current_period_end.
    """
    user_id = UUID(current_user.sub)
    result = await session.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found"
        )

    if subscription.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel subscription with status: {subscription.status}"
        )

    # Mark for cancellation
    subscription.cancel_at_period_end = True
    await session.commit()

    logger.info(f"User {user_id} cancelled subscription {subscription.id}")

    return {
        "message": "Subscription will be cancelled at the end of the billing period",
        "cancel_at": subscription.current_period_end.isoformat(),
    }


@router.post("/reactivate")
async def reactivate_subscription(
    current_user: TokenPayload = Depends(get_current_user),
    session=Depends(get_session_dep)
):
    """
    Reactivate a cancelled subscription.

    Only works if subscription is still active but marked for cancellation.
    """
    user_id = UUID(current_user.sub)
    result = await session.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found"
        )

    if not subscription.cancel_at_period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription is not scheduled for cancellation"
        )

    # Remove cancellation flag
    subscription.cancel_at_period_end = False
    await session.commit()

    logger.info(f"User {user_id} reactivated subscription {subscription.id}")

    return {
        "message": "Subscription has been reactivated",
        "status": subscription.status,
    }


# TODO: Implement these endpoints when Stripe integration is ready
# @router.post("/checkout")
# async def create_checkout_session(...)

# @router.post("/webhook")
# async def stripe_webhook(...)
