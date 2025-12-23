"""Subscription endpoints.

The current deployment focuses on making the web UI testable end-to-end.
Full Stripe-backed subscriptions live elsewhere; for now we provide a minimal,
stable contract for the frontend (/pricing and usage widget).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from .auth import TokenPayload, get_current_user

router = APIRouter(prefix="/subscription", tags=["subscription"])


def _static_plans() -> list[dict[str, Any]]:
    # Minimal set of plans the frontend can render.
    # Use sentinel values the UI already understands (e.g. 999999 => Unlimited).
    return [
        {
            "id": "free",
            "name": "free",
            "display_name": "Free",
            "price_monthly": 0,
            "price_yearly": 0,
            "max_messages_per_day": 25,
            "max_audio_minutes_per_day": 5,
            "max_characters": 3,
            "max_voice_clones": 0,
            "can_use_phone_calls": False,
            "api_access": False,
            "priority_processing": False,
        },
        {
            "id": "basic",
            "name": "basic",
            "display_name": "Basic",
            "price_monthly": 9,
            "price_yearly": 90,
            "max_messages_per_day": 250,
            "max_audio_minutes_per_day": 30,
            "max_characters": 10,
            "max_voice_clones": 0,
            "can_use_phone_calls": False,
            "api_access": False,
            "priority_processing": False,
        },
        {
            "id": "pro",
            "name": "pro",
            "display_name": "Pro",
            "price_monthly": 19,
            "price_yearly": 190,
            "max_messages_per_day": 999999,
            "max_audio_minutes_per_day": 999999,
            "max_characters": 9999,
            "max_voice_clones": 3,
            "can_use_phone_calls": True,
            "api_access": True,
            "priority_processing": True,
        },
        {
            "id": "enterprise",
            "name": "enterprise",
            "display_name": "Enterprise",
            "price_monthly": 99,
            "price_yearly": 990,
            "max_messages_per_day": 999999,
            "max_audio_minutes_per_day": 999999,
            "max_characters": 9999,
            "max_voice_clones": 10,
            "can_use_phone_calls": True,
            "api_access": True,
            "priority_processing": True,
        },
    ]


@router.get("/plans")
async def list_plans() -> dict[str, Any]:
    return {"plans": _static_plans()}


@router.get("/current")
async def current_subscription(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    # Until a real subscription system is wired, treat every authenticated user
    # as "free".
    return {
        "plan_name": "free",
        "status": "active",
    }


@router.get("/usage")
async def usage(
    _user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    # Provide the JSON shape expected by web/js/app.js (usage widget).
    return {
        "usage": {
            "messages": 0,
            "audio_minutes": 0.0,
            "tokens": 0,
            "date": date.today().isoformat(),
        },
        "limits": {
            "messages": 25,
            "audio_minutes": 5,
            "characters": 3,
        },
        "percentage": {
            "messages": 0,
            "audio": 0,
        },
        "plan": {
            "name": "free",
            "display_name": "Free",
        },
        "subscription": {
            "status": "active",
            "current_period_end": None,
        },
    }
