"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ============================================================================
# Auth Schemas
# ============================================================================

class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Schema for user info response."""
    id: UUID
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    """Schema for token refresh request."""
    refresh_token: str


# ============================================================================
# Character Schemas
# ============================================================================

class CharacterCreate(BaseModel):
    """Schema for creating a character."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    system_prompt: str = Field(..., min_length=1)
    voice_model: str = Field(default="af_bella", max_length=100)
    avatar_url: Optional[str] = None


class CharacterUpdate(BaseModel):
    """Schema for updating a character."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_model: Optional[str] = Field(None, max_length=100)
    avatar_url: Optional[str] = None


class CharacterResponse(BaseModel):
    """Schema for character response."""
    id: UUID
    name: str
    description: Optional[str]
    system_prompt: str
    voice_model: str
    rvc_model_path: Optional[str]
    rvc_index_path: Optional[str]
    avatar_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CharacterListResponse(BaseModel):
    """Schema for listing characters."""
    characters: list[CharacterResponse]


# ============================================================================
# Chat Schemas
# ============================================================================

class ChatCreate(BaseModel):
    """Schema for creating a chat."""
    character_id: UUID
    title: Optional[str] = None


class ChatResponse(BaseModel):
    """Schema for chat response."""
    id: UUID
    character_id: UUID
    title: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatListResponse(BaseModel):
    """Schema for listing chats."""
    chats: list[ChatResponse]


# ============================================================================
# Message Schemas
# ============================================================================

class MessageCreate(BaseModel):
    """Schema for creating a message."""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)
    audio_url: Optional[str] = None


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: UUID
    chat_id: UUID
    role: str
    content: str
    audio_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    """Schema for listing messages."""
    messages: list[MessageResponse]
    has_more: bool = False


# ============================================================================
# Error Schemas
# ============================================================================

class ErrorResponse(BaseModel):
    """Schema for error response."""
    detail: str


# ============================================================================
# Health Check
# ============================================================================

class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str = "ok"
    version: str = "3.0.0"
