"""Pydantic schemas for Entrance API request/response models."""

from datetime import datetime
from typing import Optional, List
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
    avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Schema for updating user profile."""
    avatar_url: Optional[str] = None


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
    system_prompt: str = Field(..., min_length=1, description="Short behavior rules and constraints")
    persona_prompt: Optional[str] = Field(None, description="Detailed character biography/lorebook")
    voice_model: str = Field(default="af_bella", max_length=100)
    avatar_url: Optional[str] = None


class CharacterUpdate(BaseModel):
    """Schema for updating a character."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    persona_prompt: Optional[str] = None
    voice_model: Optional[str] = Field(None, max_length=100)
    avatar_url: Optional[str] = None


class CharacterResponse(BaseModel):
    """Schema for character response."""
    id: UUID
    name: str
    description: Optional[str]
    system_prompt: str
    persona_prompt: Optional[str]
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
    character_avatar_url: Optional[str] = None
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
    """Schema for listing messages with offset pagination (legacy)."""
    messages: list[MessageResponse]
    has_more: bool = False


class CursorPaginatedMessages(BaseModel):
    """Schema for cursor-based paginated messages."""
    messages: List[MessageResponse]
    next_cursor: Optional[str] = None
    prev_cursor: Optional[str] = None
    has_more: bool = False
    total_count: Optional[int] = None


# ============================================================================
# Model/Voice Schemas
# ============================================================================

class VoiceModelInfo(BaseModel):
    """Information about a voice model."""
    id: str
    name: str
    description: Optional[str] = None
    language: str = "en"
    type: str = "tts"  # tts, rvc, etc.


class VoiceModelListResponse(BaseModel):
    """List of available voice models."""
    models: List[VoiceModelInfo]


class RVCModelInfo(BaseModel):
    """Information about an RVC model."""
    name: str
    model_path: str
    index_path: Optional[str] = None
    description: Optional[str] = None


class RVCModelListResponse(BaseModel):
    """List of available RVC models."""
    models: List[RVCModelInfo]


class CoreStatusResponse(BaseModel):
    """Status of the Core GPU server."""
    available: bool
    version: Optional[str] = None
    models_loaded: Optional[dict] = None
    gpu_info: Optional[dict] = None


# ============================================================================
# Error Schemas
# ============================================================================

class ErrorResponse(BaseModel):
    """Schema for error response."""
    detail: str


class ValidationErrorDetail(BaseModel):
    """Detailed validation error."""
    loc: List[str]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    """Schema for validation error response."""
    detail: List[ValidationErrorDetail]


# ============================================================================
# Health Check
# ============================================================================

class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str = "ok"
    service: str = "cognitia-entrance"
    version: str = "3.0.0"
    core_available: bool = False
