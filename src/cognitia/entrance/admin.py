"""Admin dashboard endpoints."""

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, desc
from sqlalchemy.orm import selectinload

from .auth import get_current_user
from .database import (
    User,
    Character,
    SubscriptionPlan,
    UserSubscription,
    DailyUsageCache,
    UsageRecord,
    PaymentTransaction,
    get_session_dep,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# Simple admin check - in production, use proper role-based access control
ADMIN_EMAILS = set(os.getenv("ADMIN_EMAILS", "").split(","))


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Verify user is an admin."""
    if current_user.email not in ADMIN_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


@router.get("/analytics")
async def get_analytics(
    admin: User = Depends(get_current_admin),
    session=Depends(get_session_dep)
):
    """
    Get platform analytics.

    Returns:
        - Total users
        - Active subscriptions by tier
        - Revenue metrics (MRR, total revenue)
        - Usage statistics
        - Growth metrics
    """
    # Total users
    total_users_result = await session.execute(select(func.count(User.id)))
    total_users = total_users_result.scalar()

    # Users by plan
    plan_counts_result = await session.execute(
        select(
            SubscriptionPlan.name,
            SubscriptionPlan.display_name,
            func.count(UserSubscription.id)
        )
        .join(UserSubscription, SubscriptionPlan.id == UserSubscription.plan_id)
        .group_by(SubscriptionPlan.name, SubscriptionPlan.display_name)
    )
    users_by_plan = {
        name: {"display_name": display_name, "count": count}
        for name, display_name, count in plan_counts_result.all()
    }

    # Calculate MRR (Monthly Recurring Revenue)
    mrr_result = await session.execute(
        select(
            SubscriptionPlan.price_monthly,
            func.count(UserSubscription.id)
        )
        .join(UserSubscription, SubscriptionPlan.id == UserSubscription.plan_id)
        .where(UserSubscription.status == 'active')
        .where(SubscriptionPlan.name != 'free')
        .group_by(SubscriptionPlan.price_monthly)
    )
    mrr = sum(float(price) * count for price, count in mrr_result.all())

    # Total revenue (all time)
    total_revenue_result = await session.execute(
        select(func.sum(PaymentTransaction.amount))
        .where(PaymentTransaction.status == 'succeeded')
    )
    total_revenue = float(total_revenue_result.scalar() or 0)

    # Today's usage
    today = date.today()
    usage_today_result = await session.execute(
        select(
            func.sum(DailyUsageCache.messages_count),
            func.sum(DailyUsageCache.audio_minutes),
            func.sum(DailyUsageCache.total_tokens)
        )
        .where(DailyUsageCache.date == today)
    )
    messages_today, audio_today, tokens_today = usage_today_result.first()

    # New users this month
    this_month_start = date.today().replace(day=1)
    new_users_result = await session.execute(
        select(func.count(User.id))
        .where(User.created_at >= this_month_start)
    )
    new_users_this_month = new_users_result.scalar()

    # Total characters created
    total_characters_result = await session.execute(select(func.count(Character.id)))
    total_characters = total_characters_result.scalar()

    return {
        "users": {
            "total": total_users,
            "new_this_month": new_users_this_month,
            "by_plan": users_by_plan,
        },
        "revenue": {
            "mrr": round(mrr, 2),
            "total": round(total_revenue, 2),
        },
        "usage": {
            "messages_today": int(messages_today or 0),
            "audio_minutes_today": float(audio_today or 0),
            "tokens_today": int(tokens_today or 0),
            "total_characters": total_characters,
        },
        "conversion": {
            "free_to_paid": calculate_conversion_rate(users_by_plan),
        }
    }


def calculate_conversion_rate(users_by_plan: dict) -> float:
    """Calculate conversion rate from free to paid."""
    free_count = users_by_plan.get('free', {}).get('count', 0)
    paid_count = sum(
        data['count']
        for name, data in users_by_plan.items()
        if name != 'free'
    )
    total = free_count + paid_count
    return round((paid_count / total * 100), 2) if total > 0 else 0


@router.get("/users")
async def list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    plan: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    admin: User = Depends(get_current_admin),
    session=Depends(get_session_dep)
):
    """
    List all users with filtering and pagination.

    Args:
        limit: Number of users to return
        offset: Offset for pagination
        plan: Filter by plan name (e.g., 'free', 'pro')
        search: Search by email
    """
    # Build query
    query = (
        select(User)
        .options(selectinload(User.subscription).selectinload(UserSubscription.plan))
        .order_by(desc(User.created_at))
    )

    # Apply filters
    if search:
        query = query.where(User.email.ilike(f"%{search}%"))

    if plan:
        query = (
            query.join(UserSubscription)
            .join(SubscriptionPlan)
            .where(SubscriptionPlan.name == plan)
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    query = query.limit(limit).offset(offset)

    # Execute query
    result = await session.execute(query)
    users = result.scalars().all()

    return {
        "users": [
            {
                "id": str(user.id),
                "email": user.email,
                "created_at": user.created_at.isoformat(),
                "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
                "subscription": {
                    "plan_name": user.subscription.plan.name if user.subscription else None,
                    "status": user.subscription.status if user.subscription else None,
                } if user.subscription else None,
            }
            for user in users
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/users/{user_id}")
async def get_user_details(
    user_id: UUID,
    admin: User = Depends(get_current_admin),
    session=Depends(get_session_dep)
):
    """
    Get detailed information about a specific user.

    Includes:
    - User info
    - Subscription details
    - Usage statistics
    - Characters created
    - Payment history
    """
    # Get user
    result = await session.execute(
        select(User)
        .options(
            selectinload(User.subscription).selectinload(UserSubscription.plan),
            selectinload(User.characters)
        )
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Get usage this month
    this_month_start = date.today().replace(day=1)
    usage_result = await session.execute(
        select(
            func.sum(DailyUsageCache.messages_count),
            func.sum(DailyUsageCache.audio_minutes)
        )
        .where(
            and_(
                DailyUsageCache.user_id == user_id,
                DailyUsageCache.date >= this_month_start
            )
        )
    )
    messages_month, audio_month = usage_result.first()

    # Get payment history
    payments_result = await session.execute(
        select(PaymentTransaction)
        .where(PaymentTransaction.user_id == user_id)
        .order_by(desc(PaymentTransaction.created_at))
        .limit(10)
    )
    payments = payments_result.scalars().all()

    return {
        "id": str(user.id),
        "email": user.email,
        "created_at": user.created_at.isoformat(),
        "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
        "subscription": {
            "plan": user.subscription.plan.name if user.subscription else None,
            "status": user.subscription.status if user.subscription else None,
            "period_end": user.subscription.current_period_end.isoformat() if user.subscription else None,
        } if user.subscription else None,
        "usage": {
            "messages_this_month": int(messages_month or 0),
            "audio_minutes_this_month": float(audio_month or 0),
            "characters_created": len(user.characters),
        },
        "payments": [
            {
                "id": str(payment.id),
                "amount": float(payment.amount),
                "status": payment.status,
                "created_at": payment.created_at.isoformat(),
            }
            for payment in payments
        ]
    }


@router.put("/users/{user_id}/subscription")
async def update_user_subscription(
    user_id: UUID,
    plan_name: str,
    admin: User = Depends(get_current_admin),
    session=Depends(get_session_dep)
):
    """
    Manually update a user's subscription plan.

    Use this for:
    - Granting free upgrades
    - Applying discounts
    - Manual corrections
    """
    # Get plan
    plan_result = await session.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.name == plan_name)
    )
    plan = plan_result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_name}' not found"
        )

    # Get user subscription
    sub_result = await session.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id)
    )
    subscription = sub_result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User subscription not found"
        )

    # Update subscription
    old_plan_id = subscription.plan_id
    subscription.plan_id = plan.id
    subscription.status = 'active'

    # Extend period if upgrading
    if plan.name != 'free':
        subscription.current_period_end = datetime.utcnow() + timedelta(days=30)

    await session.commit()

    logger.info(f"Admin {admin.email} changed user {user_id} from plan {old_plan_id} to {plan.id}")

    return {
        "message": f"User subscription updated to {plan.display_name}",
        "plan": plan.name,
        "status": subscription.status,
    }


@router.get("/revenue/monthly")
async def get_monthly_revenue(
    months: int = Query(default=12, ge=1, le=24),
    admin: User = Depends(get_current_admin),
    session=Depends(get_session_dep)
):
    """
    Get monthly revenue for the past N months.

    Used for revenue charts in admin dashboard.
    """
    revenue_data = []

    for i in range(months):
        # Calculate month start/end
        today = date.today()
        month_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1)

        # Get revenue for this month
        result = await session.execute(
            select(func.sum(PaymentTransaction.amount))
            .where(
                and_(
                    PaymentTransaction.created_at >= month_start,
                    PaymentTransaction.created_at < month_end,
                    PaymentTransaction.status == 'succeeded'
                )
            )
        )
        revenue = float(result.scalar() or 0)

        revenue_data.append({
            "month": month_start.strftime("%Y-%m"),
            "revenue": round(revenue, 2)
        })

    return {"data": list(reversed(revenue_data))}


import os
