"""User API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from ...dependencies import get_current_user, get_user_repository
from ...repositories import UserRepository
from ...schemas.user import UserProfileResponse, UserUpdate
from ...database import User


router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Get current user's full profile.

    Includes extended information like birthday, referral code, etc.
    """
    return UserProfileResponse.model_validate(current_user)


@router.patch("/me", response_model=UserProfileResponse)
async def update_my_profile(
    updates: UserUpdate,
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Update current user's profile.

    Can update: first_name, last_name, avatar_url, birthday
    """
    # Only update fields that were provided
    update_data = updates.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )

    updated_user = await user_repo.update(current_user.id, **update_data)

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserProfileResponse.model_validate(updated_user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Delete current user's account.

    This is a hard delete and cannot be undone.
    All associated data (characters, chats, messages) will be deleted.
    """
    deleted = await user_repo.delete(current_user.id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return None
