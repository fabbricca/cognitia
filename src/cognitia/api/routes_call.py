"""Call endpoints (LiveKit).

The web tier is responsible for authentication and token minting.
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .auth import get_user_id


router = APIRouter(prefix="/call", tags=["call"])


class CallTokenRequest(BaseModel):
    room: str = Field(min_length=1, max_length=128)
    participant_name: str | None = Field(default=None, max_length=128)


class CallTokenResponse(BaseModel):
    url: str
    token: str
    room: str
    identity: str


def _get_livekit_url() -> str:
    # For this repo we route signaling via ingress at /livekit.
    return os.getenv("LIVEKIT_URL", "wss://cognitia.iberu.me/livekit").rstrip("/")


@router.post("/token", response_model=CallTokenResponse)
async def create_call_token(
    req: CallTokenRequest,
    user_id: UUID = Depends(get_user_id),
) -> CallTokenResponse:
    try:
        from livekit import api as lkapi  # type: ignore
    except Exception as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"livekit-api not available: {e}",
        ) from e

    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not api_key or not api_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LiveKit credentials not configured",
        )

    identity = str(user_id)
    token = (
        lkapi.AccessToken(api_key=api_key, api_secret=api_secret)
        .with_identity(identity)
        .with_name(req.participant_name or identity)
        .with_grants(
            lkapi.VideoGrants(
                room_join=True,
                room=req.room,
            )
        )
        .to_jwt()
    )

    return CallTokenResponse(
        url=_get_livekit_url(),
        token=token,
        room=req.room,
        identity=identity,
    )
