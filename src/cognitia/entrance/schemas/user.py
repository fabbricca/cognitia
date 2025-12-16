"""User schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserCreate(UserBase):
    """User creation schema."""
    password: str


class UserUpdate(BaseModel):
    """User update schema."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    avatar_url: Optional[str] = None
    birthday: Optional[datetime] = None


class UserResponse(UserBase):
    """User response schema."""
    id: UUID
    avatar_url: Optional[str] = None
    role: str
    email_verified: bool
    onboarding_completed: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserProfileResponse(UserResponse):
    """Extended user profile response."""
    birthday: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    referral_code: Optional[str] = None

    class Config:
        from_attributes = True
