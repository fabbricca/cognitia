"""
Memory system data models for Cognitia.

This module defines the data structures used for storing and retrieving
memories, tasks, and knowledge in the Cognitia memory system.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Types of memory storage."""
    EPISODIC = "episodic"  # Personal experiences and conversations
    SEMANTIC = "semantic"  # General knowledge and facts
    PROCEDURAL = "procedural"  # How to perform tasks


class TaskType(str, Enum):
    """Types of tasks."""
    CALENDAR_EVENT = "calendar_event"
    REMINDER = "reminder"
    TODO = "todo"
    HABIT = "habit"


class TaskStatus(str, Enum):
    """Task completion status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MemoryItem(BaseModel):
    """Represents a single memory item in the system."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: MemoryType
    content: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    related_memories: List[str] = Field(default_factory=list)  # IDs of related memories

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConversationMemory(MemoryItem):
    """Specialized memory for conversation history."""

    type: MemoryType = MemoryType.EPISODIC
    user_message: str
    assistant_response: str
    conversation_id: str
    sentiment: Optional[float] = None  # -1 to 1 scale

    def __init__(self, **data):
        super().__init__(**data)
        self.content = f"User: {self.user_message}\nAssistant: {self.assistant_response}"


class TaskItem(BaseModel):
    """Represents a task, reminder, or calendar event."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: TaskType
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: int = Field(default=3, ge=1, le=5)  # 1=lowest, 5=highest

    # Time-based fields
    due_date: Optional[datetime] = None
    reminder_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Recurrence
    is_recurring: bool = False
    recurrence_pattern: Optional[str] = None  # Cron-like pattern

    # Location-based (for future location services)
    location: Optional[str] = None
    location_trigger: Optional[str] = None

    # Calendar event specific
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    attendees: List[str] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class KnowledgeItem(BaseModel):
    """Represents a piece of general knowledge."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    content: str
    source: str  # e.g., "wikipedia", "user_defined", "web_scraped"
    category: str
    embedding: Optional[List[float]] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    last_updated: datetime = Field(default_factory=datetime.now)
    tags: List[str] = Field(default_factory=list)
    related_concepts: List[str] = Field(default_factory=list)  # Links to other knowledge items

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class UserProfile(BaseModel):
    """User profile and preferences."""

    user_id: str = "default_user"
    name: Optional[str] = None
    preferences: Dict[str, Any] = Field(default_factory=dict)
    timezone: str = "UTC"
    language: str = "en"
    wake_words: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MemoryQuery(BaseModel):
    """Query parameters for memory retrieval."""

    query: str
    memory_type: Optional[MemoryType] = None
    tags: Optional[List[str]] = None
    date_range: Optional[tuple[datetime, datetime]] = None
    limit: int = 10
    min_importance: float = 0.0
    include_embedding: bool = False


class TaskQuery(BaseModel):
    """Query parameters for task retrieval."""

    task_type: Optional[TaskType] = None
    status: Optional[TaskStatus] = None
    priority_min: Optional[int] = None
    priority_max: Optional[int] = None
    due_before: Optional[datetime] = None
    due_after: Optional[datetime] = None
    tags: Optional[List[str]] = None
    limit: int = 50



