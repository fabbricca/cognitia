"""Stripe payment integration for subscription management."""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from .auth import get_current_user
from .database import (
    User,
    SubscriptionPlan,
    UserSubscription,
    PaymentTransaction,
    get_session_dep,
)
from .schemas_v1 import CheckoutSessionResponse, UpgradeRequest
from .email_service import email_service

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")

router = APIRouter(prefix="/api/payment", tags=["payment"])


class PaymentService:
    """Service for handling Stripe payments."""

    @staticmethod
    async def create_checkout_session(
        user: User,
        plan: SubscriptionPlan,
        billing_cycle: str,
        session
    ) -> str:
        """
        Create a Stripe checkout session.

        Args:
            user: User object
            plan: SubscriptionPlan object
            billing_cycle: 'monthly' or 'yearly'
            session: Database session

        Returns:
            Stripe checkout URL
        """
        try:
            # Determine price based on billing cycle
            if billing_cycle == "yearly" and plan.price_yearly:
                price = float(plan.price_yearly)
                interval = "year"
            else:
                price = float(plan.price_monthly)
                interval = "month"

            # Create checkout session
            checkout_session = stripe.checkout.Session.create(
                customer_email=user.email,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': plan.display_name,
                            'description': f"{plan.max_messages_per_day} messages/day, {plan.max_audio_minutes_per_day} audio minutes/day",
                        },
                        'unit_amount': int(price * 100),  # Convert to cents
                        'recurring': {'interval': interval}
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=f'{FRONTEND_URL}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}',
                cancel_url=f'{FRONTEND_URL}/subscription/canceled',
                client_reference_id=str(user.id),
                metadata={
                    'user_id': str(user.id),
                    'plan_id': str(plan.id),
                    'plan_name': plan.name,
                    'billing_cycle': billing_cycle,
                }
            )

            logger.info(f"Created checkout session for user {user.id}, plan {plan.name}")
            return checkout_session.url

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Payment processing error: {str(e)}"
            )

    @staticmethod
    async def handle_checkout_completed(event_data: dict, session_db):
        """
        Handle successful checkout.

        Creates or updates user subscription.
        """
        session_data = event_data['object']
        user_id = UUID(session_data['metadata']['user_id'])
        plan_id = UUID(session_data['metadata']['plan_id'])

        logger.info(f"Processing checkout completion for user {user_id}")

        # Get or create subscription
        result = await session_db.execute(
            select(UserSubscription).where(UserSubscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        # Calculate billing period
        now = datetime.utcnow()
        billing_cycle = session_data['metadata'].get('billing_cycle', 'monthly')
        if billing_cycle == 'yearly':
            period_end = now + timedelta(days=365)
        else:
            period_end = now + timedelta(days=30)

        if subscription:
            # Update existing subscription
            subscription.plan_id = plan_id
            subscription.status = 'active'
            subscription.current_period_start = now
            subscription.current_period_end = period_end
            subscription.stripe_subscription_id = session_data.get('subscription')
            subscription.stripe_customer_id = session_data.get('customer')
            subscription.cancel_at_period_end = False
        else:
            # Create new subscription
            subscription = UserSubscription(
                user_id=user_id,
                plan_id=plan_id,
                status='active',
                current_period_start=now,
                current_period_end=period_end,
                stripe_subscription_id=session_data.get('subscription'),
                stripe_customer_id=session_data.get('customer'),
            )
            session_db.add(subscription)

        # Record transaction
        transaction = PaymentTransaction(
            user_id=user_id,
            subscription_id=subscription.id,
            amount=session_data.get('amount_total', 0) / 100,  # Convert from cents
            currency='USD',
            status='succeeded',
            provider='stripe',
            provider_transaction_id=session_data.get('payment_intent'),
            description=f"Subscription: {session_data['metadata']['plan_name']}"
        )
        session_db.add(transaction)

        await session_db.commit()
        logger.info(f"✓ Subscription activated for user {user_id}")

        # Send confirmation emails (non-blocking)
        try:
            import asyncio

            # Get user and plan for email
            user_result = await session_db.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()

            plan_result = await session_db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
            )
            plan = plan_result.scalar_one_or_none()

            if user and plan:
                # Send payment success email to user
                asyncio.create_task(
                    email_service.send_payment_success(
                        to_email=user.email,
                        user_name=user.email.split('@')[0],
                        plan_name=plan.display_name,
                        amount=float(transaction.amount),
                        transaction_id=str(transaction.id)
                    )
                )

                # Send notification to admin
                asyncio.create_task(
                    email_service.send_admin_new_subscription(
                        plan_name=plan.display_name,
                        user_email=user.email,
                        amount=float(transaction.amount)
                    )
                )

                logger.info(f"Queued confirmation emails for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send confirmation emails: {e}", exc_info=True)

    @staticmethod
    async def handle_subscription_deleted(event_data: dict, session_db):
        """
        Handle subscription cancellation.

        Downgrades user to free tier.
        """
        subscription_data = event_data['object']
        stripe_sub_id = subscription_data['id']

        logger.info(f"Processing subscription deletion: {stripe_sub_id}")

        # Find subscription by Stripe ID
        result = await session_db.execute(
            select(UserSubscription).where(
                UserSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            logger.warning(f"Subscription not found for Stripe ID: {stripe_sub_id}")
            return

        # Get free plan
        free_plan_result = await session_db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.name == 'free')
        )
        free_plan = free_plan_result.scalar_one()

        # Downgrade to free
        old_plan_id = subscription.plan_id
        subscription.plan_id = free_plan.id
        subscription.status = 'canceled'
        subscription.cancel_at_period_end = False

        await session_db.commit()
        logger.info(f"✓ User downgraded to free tier: {subscription.user_id}")

        # Send cancellation email (non-blocking)
        try:
            import asyncio

            # Get user and plan info
            user_result = await session_db.execute(
                select(User).where(User.id == subscription.user_id)
            )
            user = user_result.scalar_one_or_none()

            plan_result = await session_db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.id == old_plan_id)
            )
            old_plan = plan_result.scalar_one_or_none()

            if user and old_plan:
                asyncio.create_task(
                    email_service.send_subscription_canceled(
                        to_email=user.email,
                        user_name=user.email.split('@')[0],
                        plan_name=old_plan.display_name,
                        end_date=subscription.current_period_end.strftime('%B %d, %Y')
                    )
                )
                logger.info(f"Queued cancellation email for user {subscription.user_id}")
        except Exception as e:
            logger.error(f"Failed to send cancellation email: {e}", exc_info=True)

    @staticmethod
    async def handle_payment_failed(event_data: dict, session_db):
        """
        Handle failed payment.

        Marks subscription as past_due.
        """
        invoice_data = event_data['object']
        stripe_sub_id = invoice_data.get('subscription')

        logger.warning(f"Payment failed for subscription: {stripe_sub_id}")

        # Find subscription
        result = await session_db.execute(
            select(UserSubscription).where(
                UserSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        subscription = result.scalar_one_or_none()

        if subscription:
            subscription.status = 'past_due'
            await session_db.commit()
            logger.info(f"Subscription marked as past_due: {subscription.id}")

            # Send payment failed email (non-blocking)
            try:
                import asyncio

                # Get user and plan info
                user_result = await session_db.execute(
                    select(User).where(User.id == subscription.user_id)
                )
                user = user_result.scalar_one_or_none()

                plan_result = await session_db.execute(
                    select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
                )
                plan = plan_result.scalar_one_or_none()

                if user and plan:
                    # Get failure reason from invoice
                    failure_reason = invoice_data.get('last_finalization_error', {}).get('message')

                    asyncio.create_task(
                        email_service.send_payment_failed(
                            to_email=user.email,
                            user_name=user.email.split('@')[0],
                            plan_name=plan.display_name,
                            reason=failure_reason
                        )
                    )
                    logger.info(f"Queued payment failed email for user {subscription.user_id}")
            except Exception as e:
                logger.error(f"Failed to send payment failed email: {e}", exc_info=True)


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout(
    request_data: UpgradeRequest,
    current_user: User = Depends(get_current_user),
    session=Depends(get_session_dep)
):
    """
    Create a Stripe checkout session for subscription upgrade.

    Args:
        request_data: Plan ID and billing cycle
        current_user: Authenticated user
        session: Database session

    Returns:
        Checkout URL and session ID
    """
    # Get plan
    result = await session.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == request_data.plan_id)
    )
    plan = result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )

    # Don't allow downgrade to free via checkout
    if plan.name == 'free':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot purchase free plan"
        )

    # Create checkout session
    checkout_url = await PaymentService.create_checkout_session(
        user=current_user,
        plan=plan,
        billing_cycle=request_data.billing_cycle,
        session=session
    )

    return CheckoutSessionResponse(
        checkout_url=checkout_url,
        session_id=checkout_url.split('/')[-1]  # Extract session ID from URL
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    session=Depends(get_session_dep)
):
    """
    Handle Stripe webhook events.

    This endpoint receives notifications from Stripe about:
    - Successful payments
    - Failed payments
    - Subscription cancellations
    - etc.
    """
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.error("Invalid webhook payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    event_type = event['type']
    logger.info(f"Received Stripe webhook: {event_type}")

    try:
        if event_type == 'checkout.session.completed':
            await PaymentService.handle_checkout_completed(event['data'], session)

        elif event_type == 'customer.subscription.deleted':
            await PaymentService.handle_subscription_deleted(event['data'], session)

        elif event_type == 'invoice.payment_failed':
            await PaymentService.handle_payment_failed(event['data'], session)

        elif event_type == 'customer.subscription.updated':
            # Handle subscription updates (plan changes, etc.)
            logger.info(f"Subscription updated: {event['data']['object']['id']}")

        else:
            logger.info(f"Unhandled event type: {event_type}")

    except Exception as e:
        logger.error(f"Error processing webhook {event_type}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

    return {"status": "success"}


@router.get("/portal")
async def customer_portal(
    current_user: User = Depends(get_current_user),
    session=Depends(get_session_dep)
):
    """
    Create a Stripe Customer Portal session.

    Allows users to manage their subscription, update payment methods, etc.
    """
    # Get user's subscription
    result = await session.execute(
        select(UserSubscription).where(UserSubscription.user_id == current_user.id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found"
        )

    try:
        # Create portal session
        portal_session = stripe.billing_portal.Session.create(
            customer=subscription.stripe_customer_id,
            return_url=f'{FRONTEND_URL}/subscription',
        )

        return {"url": portal_session.url}

    except stripe.error.StripeError as e:
        logger.error(f"Error creating portal session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create portal session"
        )
