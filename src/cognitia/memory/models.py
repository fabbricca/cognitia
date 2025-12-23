"""Pydantic models for Memory Add-on API."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    """Request model for ingesting conversation."""

    user_id: str = Field(..., description="User ID")
    character_id: str = Field(..., description="Character ID")
    user_message: str = Field(..., description="User's message")
    assistant_response: str = Field(..., description="Assistant's response")
    extracted_facts: List[Dict[str, Any]] = Field(
        default_factory=list, description="Facts extracted from conversation"
    )
    timestamp: datetime = Field(..., description="Conversation timestamp")


class IngestResponse(BaseModel):
    """Response model for ingestion."""

    success: bool = Field(..., description="Whether ingestion succeeded")
    entities_created: int = Field(0, description="Number of entities created")
    relationships_created: int = Field(0, description="Number of relationships created")
    episode_id: Optional[str] = Field(None, description="ID of stored episode")
    salience_score: float = Field(0.0, description="Calculated salience score")
    status: Optional[str] = Field(None, description="Status message with additional details")


class RetrieveRequest(BaseModel):
    """Request model for retrieving memory context."""

    user_id: str = Field(..., description="User ID")
    character_id: str = Field(..., description="Character ID")
    query: Optional[str] = Field(None, description="Optional query for semantic search")
    limit: int = Field(10, description="Maximum number of memories to retrieve", ge=1, le=50)


class MemoryItem(BaseModel):
    """Individual memory item."""

    type: str = Field(..., description="Type: 'fact', 'episode', or 'persona'")
    content: str = Field(..., description="Memory content")
    score: float = Field(..., description="Relevance/importance score")
    timestamp: Optional[datetime] = Field(None, description="When this memory was created")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class RetrieveResponse(BaseModel):
    """Response model for memory retrieval."""

    context: str = Field(..., description="Formatted context block for LLM")
    memories: List[MemoryItem] = Field(default_factory=list, description="Individual memory items")
    persona_summary: Optional[str] = Field(None, description="Distilled persona summary")
    total_tokens: int = Field(0, description="Estimated token count of context")


class PersonRequest(BaseModel):
    """Request model for getting Person object."""

    person_name: str = Field(..., description="Name of person to retrieve")
    user_id: str = Field(..., description="User ID for scoping")
    character_id: str = Field(..., description="Character ID for scoping")


class PersonResponse(BaseModel):
    """Response model for Person object."""

    name: str = Field(..., description="Person's name")
    entity_type: str = Field(..., description="Type: person, place, event")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Person properties")
    relationships: List[Dict[str, Any]] = Field(
        default_factory=list, description="Relationships with other entities"
    )


# =============================================================================
# Knowledge Graph (Graphiti/Neo4j) Export
# =============================================================================


class GraphNode(BaseModel):
    """A graph node suitable for UI rendering."""

    id: str = Field(..., description="Stable node identifier (Neo4j element id)")
    labels: List[str] = Field(default_factory=list, description="Neo4j labels")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Node properties")


class GraphEdge(BaseModel):
    """A graph edge suitable for UI rendering."""

    id: str = Field(..., description="Stable edge identifier (Neo4j element id)")
    type: str = Field(..., description="Relationship type")
    source: str = Field(..., description="Source node id")
    target: str = Field(..., description="Target node id")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Edge properties")


class GraphResponse(BaseModel):
    """Response model for exporting a subgraph."""

    available: bool = Field(..., description="Whether graph export is available")
    group_id: Optional[str] = Field(None, description="Graphiti group id used for scoping")
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


class DistillRequest(BaseModel):
    """Request model for persona distillation."""

    user_id: str = Field(..., description="User ID")
    character_id: str = Field(..., description="Character ID")
    force: bool = Field(False, description="Force distillation even if recent")


class DistillResponse(BaseModel):
    """Response model for persona distillation."""

    success: bool = Field(..., description="Whether distillation succeeded")
    persona: Dict[str, Any] = Field(default_factory=dict, description="Distilled persona profile")
    facts_processed: int = Field(0, description="Number of facts used")
    episodes_processed: int = Field(0, description="Number of episodes used")
    token_count: int = Field(0, description="Token count of persona")


class PersonaGetResponse(BaseModel):
    """Response model for getting persona."""

    exists: bool = Field(..., description="Whether persona exists")
    persona: Optional[Dict[str, Any]] = Field(None, description="Persona profile if exists")
    updated_at: Optional[str] = Field(None, description="When persona was last updated")
    version: Optional[int] = Field(None, description="Persona version")


class PersonaDeleteResponse(BaseModel):
    """Response model for deleting persona."""

    success: bool = Field(..., description="Whether deletion succeeded")
    existed: bool = Field(..., description="Whether persona existed before deletion")


class PruneRequest(BaseModel):
    """Request model for pruning old memories."""

    days: int = Field(180, description="Prune memories older than this", ge=1)
    min_salience: float = Field(0.3, description="Only prune below this salience", ge=0.0, le=1.0)


class PruneResponse(BaseModel):
    """Response model for memory pruning."""

    success: bool = Field(..., description="Whether pruning succeeded")
    episodes_pruned: int = Field(0, description="Number of episodes removed")
    entities_pruned: int = Field(0, description="Number of entities removed")


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Service status")
    graphiti_connected: bool = Field(..., description="Neo4j/Graphiti connection status")
    qdrant_connected: bool = Field(..., description="Qdrant connection status")
    ollama_available: bool = Field(..., description="Ollama availability")
