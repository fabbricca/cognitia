"""Character schemas."""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel


class CharacterBase(BaseModel):
    """Base character schema."""
    name: str
    description: Optional[str] = None
    system_prompt: str
    persona_prompt: Optional[str] = None
    voice_model: str = "af_bella"
    prompt_template: str = "pygmalion"


class CharacterCreate(CharacterBase):
    """Character creation schema."""
    is_public: bool = False
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    rvc_model_path: Optional[str] = None
    rvc_index_path: Optional[str] = None


class CharacterUpdate(BaseModel):
    """Character update schema."""
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    persona_prompt: Optional[str] = None
    voice_model: Optional[str] = None
    prompt_template: Optional[str] = None
    avatar_url: Optional[str] = None
    is_public: Optional[bool] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    rvc_model_path: Optional[str] = None
    rvc_index_path: Optional[str] = None


class CharacterResponse(CharacterBase):
    """Character response schema."""
    id: UUID
    user_id: UUID
    avatar_url: Optional[str] = None
    is_public: bool
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CharacterWithVoiceResponse(CharacterResponse):
    """Character response with voice model info."""
    rvc_model_path: Optional[str] = None
    rvc_index_path: Optional[str] = None
    has_voice_access: bool = False

    class Config:
        from_attributes = True


class CharacterListResponse(BaseModel):
    """Paginated character list response."""
    characters: List[CharacterResponse]
    total: int
    offset: int
    limit: int


class VoicePermissionRequest(BaseModel):
    """Voice permission grant/revoke request."""
    user_id: UUID
