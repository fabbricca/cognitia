"""Auth router (API side).

Token issuance is handled by the dedicated `cognitia-auth` service.
This router keeps only user-introspection endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import TokenPayload, get_current_user
from .database import User, get_session
from .schemas import UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserResponse)
async def get_me(
    payload: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get current user info."""
    user_id = UUID(payload.sub)
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        # First API call for a new auth user; create a local row.
        email = payload.email or f"{user_id}@external-auth.local"
        user = User(
            id=user_id,
            email=email,
            password_hash="external-auth",
            email_verified=True,
        )
        session.add(user)
        try:
            await session.commit()
            await session.refresh(user)
        except Exception:
            await session.rollback()
            # If creation failed (race), re-fetch.
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to provision user",
                )
    
    return UserResponse.model_validate(user)
