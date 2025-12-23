"""Pydantic schemas for the Memory System API."""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# User Facts
# =============================================================================

class UserFactBase(BaseModel):
    """Base schema for user facts."""
    category: str = Field(..., description="Fact category: personal, preference, relationship, life_event, trait")
    key: str = Field(..., min_length=1, max_length=255)
    value: str = Field(..., min_length=1)


class UserFactCreate(UserFactBase):
    """Schema for creating a user fact."""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UserFactUpdate(BaseModel):
    """Schema for updating a user fact."""
    category: Optional[str] = Field(None, description="Fact category")
    key: Optional[str] = Field(None, min_length=1, max_length=255)
    value: Optional[str] = Field(None, min_length=1)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class UserFactResponse(UserFactBase):
    """Schema for user fact response."""
    id: UUID
    confidence: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserFactListResponse(BaseModel):
    """Schema for list of user facts."""
    facts: List[UserFactResponse]
    total: int


# =============================================================================
# Memories
# =============================================================================

class MemoryBase(BaseModel):
    """Base schema for memories."""
    memory_type: str = Field(..., description="Memory type: episodic, semantic, event")
    content: str
    summary: Optional[str] = None
    emotional_tone: Optional[str] = None


class MemoryCreate(MemoryBase):
    """Schema for creating a memory."""
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class MemoryUpdate(BaseModel):
    """Schema for updating a memory."""
    content: Optional[str] = None
    summary: Optional[str] = None
    emotional_tone: Optional[str] = None
    importance: Optional[float] = Field(None, ge=0.0, le=1.0)


class MemoryResponse(MemoryBase):
    """Schema for memory response."""
    id: UUID
    importance: float
    access_count: int
    created_at: datetime
    last_accessed: datetime

    class Config:
        from_attributes = True


class MemoryListResponse(BaseModel):
    """Schema for list of memories."""
    memories: List[MemoryResponse]
    total: int


class MemorySearchRequest(BaseModel):
    """Schema for memory search."""
    query: str
    memory_type: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=50)


# =============================================================================
# Relationship
# =============================================================================

class InsideJoke(BaseModel):
    """Schema for an inside joke."""
    joke: str
    context: str
    created_at: datetime


class Milestone(BaseModel):
    """Schema for a relationship milestone."""
    name: str
    date: datetime
    description: str


class RelationshipResponse(BaseModel):
    """Schema for relationship status response."""
    id: UUID
    character_id: UUID
    stage: str  # stranger, acquaintance, friend, close_friend, confidant, soulmate
    trust_level: int  # 0-100
    sentiment_score: int  # -100 to +100
    total_conversations: int
    total_messages: int
    first_conversation: Optional[datetime]
    last_conversation: Optional[datetime]
    inside_jokes: List[InsideJoke] = []
    milestones: List[Milestone] = []
    created_at: datetime

    @field_validator('inside_jokes', mode='before')
    @classmethod
    def validate_inside_jokes(cls, v):
        """Convert None to empty list and parse JSONB data."""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []
    
    @field_validator('milestones', mode='before')
    @classmethod
    def validate_milestones(cls, v):
        """Convert None to empty list and parse JSONB data."""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []

    class Config:
        from_attributes = True


class RelationshipUpdate(BaseModel):
    """Schema for updating relationship status."""
    stage: Optional[str] = Field(None, description="Relationship stage")
    trust_level: Optional[int] = Field(None, ge=0, le=100)
    sentiment_score: Optional[int] = Field(None, ge=-100, le=100)


class RelationshipListResponse(BaseModel):
    """Schema for list of relationships."""
    relationships: List[RelationshipResponse]


# =============================================================================
# Diary
# =============================================================================

class DiaryEntryResponse(BaseModel):
    """Schema for diary entry response."""
    id: UUID
    entry_date: date
    entry_type: str  # daily, weekly, monthly
    summary: str
    highlights: List[str] = []
    emotional_summary: Optional[str]
    topics_discussed: List[str] = []
    created_at: datetime

    class Config:
        from_attributes = True


class DiaryListResponse(BaseModel):
    """Schema for list of diary entries."""
    entries: List[DiaryEntryResponse]
    total: int


# =============================================================================
# Memory Context (for debugging/display)
# =============================================================================

class MemoryContextResponse(BaseModel):
    """Schema for full memory context."""
    relationship: Optional[RelationshipResponse]
    facts: List[UserFactResponse]
    recent_memories: List[MemoryResponse]
    context_string: str  # The actual context that would be injected into LLM


# =============================================================================
# Knowledge Graph (Memory Add-on / Graphiti)
# =============================================================================


class GraphNode(BaseModel):
    id: str
    labels: List[str] = Field(default_factory=list)
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    type: str
    source: str
    target: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    available: bool
    group_id: Optional[str] = None
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
