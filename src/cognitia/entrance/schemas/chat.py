"""Chat and message Pydantic schemas for API v2."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# Chat Schemas
# ============================================================================

class ChatBase(BaseModel):
    """Base chat schema."""
    title: Optional[str] = Field(None, max_length=200)


class ChatCreate(BaseModel):
    """Schema for creating a chat."""
    title: Optional[str] = Field(None, max_length=200)
    character_ids: List[UUID] = Field(default_factory=list, description="Characters to add to chat")
    participant_user_ids: List[UUID] = Field(default_factory=list, description="Users to invite to group chat")


class ChatUpdate(BaseModel):
    """Schema for updating a chat."""
    title: Optional[str] = Field(None, max_length=200)


class ChatParticipantResponse(BaseModel):
    """Schema for chat participant."""
    user_id: UUID
    role: str = "member"  # Default role, not stored in DB yet
    joined_at: datetime
    last_read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatCharacterResponse(BaseModel):
    """Schema for chat character."""
    character_id: UUID
    character_name: str
    added_at: datetime

    class Config:
        from_attributes = True


class ChatResponse(BaseModel):
    """Schema for chat response."""
    id: UUID
    title: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Optional expanded fields
    participants: Optional[List[ChatParticipantResponse]] = None
    characters: Optional[List[ChatCharacterResponse]] = None
    unread_count: Optional[int] = None

    class Config:
        from_attributes = True


class ChatDetailResponse(ChatResponse):
    """Schema for detailed chat response with participants and characters."""
    participants: List[ChatParticipantResponse]
    characters: List[ChatCharacterResponse]


class AddParticipantRequest(BaseModel):
    """Schema for adding a participant to a chat."""
    user_id: UUID
    role: str = Field(default="member", pattern="^(owner|admin|member)$")


class AddCharacterRequest(BaseModel):
    """Schema for adding a character to a chat."""
    character_id: UUID


# ============================================================================
# Message Schemas
# ============================================================================

class MessageBase(BaseModel):
    """Base message schema."""
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1, max_length=10000)


class MessageCreate(BaseModel):
    """Schema for creating a message."""
    role: str = Field(default="user", pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1, max_length=10000)
    character_id: Optional[UUID] = Field(None, description="Character for assistant messages")
    audio_url: Optional[str] = Field(None, description="URL/data URI for audio message")


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: UUID
    chat_id: UUID
    role: str
    content: str
    audio_url: Optional[str] = None
    created_at: datetime

    # Optional fields
    character_id: Optional[UUID] = None
    character_name: Optional[str] = None

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    """Schema for paginated message list."""
    messages: List[MessageResponse]
    total_count: int
    has_more: bool = False


class SendMessageRequest(BaseModel):
    """Schema for sending a message in a chat."""
    content: str = Field(..., min_length=1, max_length=10000)
    character_id: Optional[UUID] = Field(None, description="Character to respond (for group chats)")
