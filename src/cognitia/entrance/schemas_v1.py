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
    prompt_template: str = Field(default="pygmalion", description="Prompt format: pygmalion, alpaca, or chatml")
    avatar_url: Optional[str] = None


class CharacterUpdate(BaseModel):
    """Schema for updating a character."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    persona_prompt: Optional[str] = None
    voice_model: Optional[str] = Field(None, max_length=100)
    prompt_template: Optional[str] = Field(None, description="Prompt format: pygmalion, alpaca, or chatml")
    avatar_url: Optional[str] = None


class CharacterResponse(BaseModel):
    """Schema for character response."""
    id: UUID
    name: str
    description: Optional[str]
    system_prompt: str
    persona_prompt: Optional[str]
    voice_model: str
    prompt_template: str
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


# ============================================================================
# Subscription Schemas
# ============================================================================

class SubscriptionPlanResponse(BaseModel):
    """Schema for subscription plan response."""
    id: str
    name: str
    display_name: str
    price_monthly: float
    price_yearly: Optional[float] = None

    # Limits
    max_characters: int
    max_messages_per_day: int
    max_audio_minutes_per_day: int
    max_voice_clones: int
    max_context_messages: int

    # Features
    can_use_custom_voices: bool
    can_use_phone_calls: bool
    can_access_premium_models: bool
    can_export_conversations: bool
    priority_processing: bool
    api_access: bool
    webhook_support: bool

    class Config:
        from_attributes = True


class UserSubscriptionResponse(BaseModel):
    """Schema for user's subscription response."""
    id: str
    user_id: str
    plan_id: str
    plan_name: str
    plan_display_name: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool

    # Convenience fields
    limits: dict
    usage: dict
    features: dict

    class Config:
        from_attributes = True


class UsageResponse(BaseModel):
    """Schema for usage statistics response."""
    usage: dict  # {messages, audio_minutes, tokens, date}
    limits: dict  # {messages, audio_minutes, characters}
    percentage: dict  # {messages, audio}
    plan: dict  # {name, display_name}
    subscription: dict  # {status, current_period_end}


class UpgradeRequest(BaseModel):
    """Schema for subscription upgrade request."""
    plan_id: UUID
    billing_cycle: str = Field(..., pattern="^(monthly|yearly)$")


class CheckoutSessionResponse(BaseModel):
    """Schema for Stripe checkout session response."""
    checkout_url: str
    session_id: str
