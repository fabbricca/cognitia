"""Memory router: endpoints for memory retrieval and persona management.

The web UI expects REST endpoints under /api/memory/{character_id}/... for:
- graph snapshot
- facts CRUD
- memories CRUD
- relationship get/update
- diary list

This API deployment keeps those endpoints available even when full DB-backed
memory features are not yet wired into this service.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_user_id
from .database import Character, Chat, get_session
from .memory_client import memory_client

router = APIRouter(prefix="/memory", tags=["memory"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# In-memory placeholders for UI CRUD flows (non-durable).
_facts_store: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
_relationship_store: dict[tuple[str, str], dict[str, Any]] = {}


class MemoryContextRequest(BaseModel):
    """Request model for retrieving memory context."""

    chat_id: UUID = Field(..., description="Chat ID")
    query: Optional[str] = Field(None, description="Optional query for semantic search")
    limit: int = Field(10, description="Maximum number of memories", ge=1, le=50)


class MemoryContextResponse(BaseModel):
    """Response model for memory context."""

    context: str = Field("", description="Formatted context block")
    persona_summary: Optional[dict] = Field(None, description="Persona summary")
    memories_count: int = Field(0, description="Number of memories retrieved")


class PersonaDistillRequest(BaseModel):
    """Request model for triggering persona distillation."""

    character_id: UUID = Field(..., description="Character ID")
    force: bool = Field(False, description="Force distillation even if recent")


class PersonaDistillResponse(BaseModel):
    """Response model for persona distillation."""

    success: bool = Field(..., description="Whether distillation succeeded")
    persona: Optional[dict] = Field(None, description="Distilled persona")
    facts_processed: int = Field(0, description="Number of facts used")
    episodes_processed: int = Field(0, description="Number of episodes used")
    token_count: int = Field(0, description="Token count of persona")


class PersonaGetResponse(BaseModel):
    """Response model for getting persona."""

    exists: bool = Field(..., description="Whether persona exists")
    persona: Optional[dict] = Field(None, description="Persona profile")
    updated_at: Optional[str] = Field(None, description="When persona was updated")


@router.post("/context", response_model=MemoryContextResponse)
async def get_memory_context(
    request: MemoryContextRequest,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Retrieve memory context for a conversation.

    This endpoint:
    1. Verifies the user owns the chat
    2. Retrieves relevant memories from the memory service
    3. Returns formatted context for LLM injection
    """
    # Verify chat ownership
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(
            Chat.id == request.chat_id,
            Character.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()

    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )

    # Retrieve memory context from memory service
    try:
        memory_response = await memory_client.retrieve_context(
            user_id=user_id,
            character_id=chat.character_id,
            query=request.query,
            limit=request.limit,
        )

        if not memory_response:
            logger.warning(f"Memory service unavailable for user={user_id}")
            return MemoryContextResponse(
                context="",
                persona_summary=None,
                memories_count=0,
            )

        # Get persona summary separately
        persona = await memory_client.get_persona(
            user_id=user_id,
            character_id=chat.character_id,
        )

        return MemoryContextResponse(
            context=memory_response.get("context", ""),
            persona_summary=persona,
            memories_count=len(memory_response.get("memories", [])),
        )

    except Exception as e:
        logger.error(f"Memory context retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Memory retrieval failed: {str(e)}",
        )


@router.get("/{character_id}/graph")
async def get_memory_graph(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Return a UI-friendly knowledge graph snapshot (nodes + edges)."""
    # Verify character ownership
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    graph = await memory_client.get_graph(user_id=user_id, character_id=character_id)
    if not graph:
        return {
            "available": False,
            "group_id": f"{user_id}_{character_id}",
            "nodes": [],
            "edges": [],
        }
    return graph


@router.get("/{character_id}/context")
async def get_memory_context_ui(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Return a minimal memory context object used by the UI."""
    # Verify character ownership
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    key = (str(user_id), str(character_id))
    facts = list((_facts_store.get(key) or {}).values())
    relationship = _relationship_store.get(key)
    if relationship is None:
        relationship = {
            "id": str(uuid4()),
            "character_id": str(character_id),
            "stage": "acquaintance",
            "trust_level": 50,
            "sentiment_score": 0,
            "total_conversations": 0,
            "total_messages": 0,
            "first_conversation": None,
            "last_conversation": None,
            "inside_jokes": [],
            "milestones": [],
            "created_at": _now_iso(),
        }
    return {
        "relationship": relationship,
        "facts": facts,
        "recent_memories": [],
        "context_string": "",
    }


@router.get("/{character_id}/facts")
async def list_facts(
    character_id: UUID,
    category: Optional[str] = Query(None),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    key = (str(user_id), str(character_id))
    facts = list((_facts_store.get(key) or {}).values())
    if category:
        facts = [f for f in facts if f.get("category") == category]
    return {"facts": facts, "total": len(facts)}


@router.post("/{character_id}/facts")
async def create_fact(
    character_id: UUID,
    payload: dict,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    fact_id = str(uuid4())
    fact = {
        "id": fact_id,
        "category": payload.get("category") or "personal",
        "key": payload.get("key") or "",
        "value": payload.get("value") or "",
        "confidence": float(payload.get("confidence") or 1.0),
        "updated_at": _now_iso(),
    }
    key = (str(user_id), str(character_id))
    bucket = _facts_store.setdefault(key, {})
    bucket[fact_id] = fact
    return fact


@router.put("/{character_id}/facts/{fact_id}")
async def update_fact(
    character_id: UUID,
    fact_id: UUID,
    payload: dict,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    key = (str(user_id), str(character_id))
    bucket = _facts_store.setdefault(key, {})
    existing = bucket.get(str(fact_id))
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")

    for field in ("category", "key", "value", "confidence"):
        if field in payload and payload[field] is not None:
            existing[field] = payload[field]
    if "confidence" in existing:
        existing["confidence"] = float(existing["confidence"])
    existing["updated_at"] = _now_iso()
    return existing


@router.delete("/{character_id}/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    character_id: UUID,
    fact_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    key = (str(user_id), str(character_id))
    bucket = _facts_store.get(key) or {}
    bucket.pop(str(fact_id), None)


@router.get("/{character_id}/memories")
async def list_memories(
    character_id: UUID,
    memory_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    # Not yet wired in this API; return empty list for UI.
    _ = memory_type
    _ = limit
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return {"memories": [], "total": 0}


@router.put("/{character_id}/memories/{memory_id}")
async def update_memory_ui(
    character_id: UUID,
    memory_id: UUID,
    _payload: dict,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    # UI only calls this when there are memories; since we don't provide any,
    # return 404 so it can error-toast gracefully.
    _ = memory_id
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")


@router.delete("/{character_id}/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_ui(
    character_id: UUID,
    memory_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    _ = memory_id
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")


@router.get("/{character_id}/relationship")
async def get_relationship_ui(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    key = (str(user_id), str(character_id))
    rel = _relationship_store.get(key)
    if rel is None:
        rel = {
            "id": str(uuid4()),
            "character_id": str(character_id),
            "stage": "acquaintance",
            "trust_level": 50,
            "sentiment_score": 0,
            "total_conversations": 0,
            "total_messages": 0,
            "first_conversation": None,
            "last_conversation": None,
            "inside_jokes": [],
            "milestones": [],
            "created_at": _now_iso(),
        }
        _relationship_store[key] = rel
    return rel


@router.put("/{character_id}/relationship")
async def update_relationship_ui(
    character_id: UUID,
    payload: dict,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    rel = await get_relationship_ui(character_id=character_id, user_id=user_id, session=session)
    stage = payload.get("stage")
    if stage is not None:
        rel["stage"] = stage

    trust_level = payload.get("trust_level")
    if trust_level is not None:
        rel["trust_level"] = int(trust_level)
    _relationship_store[(str(user_id), str(character_id))] = rel
    return rel


@router.delete("/{character_id}/relationship/inside-jokes/{joke_index}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inside_joke_ui(
    character_id: UUID,
    joke_index: int,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    rel = await get_relationship_ui(character_id=character_id, user_id=user_id, session=session)
    jokes = rel.get("inside_jokes") or []
    if 0 <= joke_index < len(jokes):
        jokes.pop(joke_index)
    rel["inside_jokes"] = jokes
    _relationship_store[(str(user_id), str(character_id))] = rel


@router.delete("/{character_id}/relationship/milestones/{milestone_index}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_milestone_ui(
    character_id: UUID,
    milestone_index: int,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    rel = await get_relationship_ui(character_id=character_id, user_id=user_id, session=session)
    milestones = rel.get("milestones") or []
    if 0 <= milestone_index < len(milestones):
        milestones.pop(milestone_index)
    rel["milestones"] = milestones
    _relationship_store[(str(user_id), str(character_id))] = rel


@router.get("/{character_id}/diary")
async def list_diary_entries_ui(
    character_id: UUID,
    entry_type: Optional[str] = Query("daily"),
    limit: int = Query(30, ge=1, le=100),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    _ = entry_type
    _ = limit
    result = await session.execute(
        select(Character).where(Character.id == character_id, Character.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return {"entries": [], "total": 0}


@router.post("/persona/distill", response_model=PersonaDistillResponse)
async def distill_persona(
    request: PersonaDistillRequest,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Trigger persona distillation for a user-character pair.

    This endpoint:
    1. Verifies the user owns the character
    2. Triggers persona distillation in the memory service
    3. Returns the distilled persona profile
    """
    # Verify character ownership
    result = await session.execute(
        select(Character).where(
            Character.id == request.character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()

    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    # Trigger distillation
    try:
        distill_response = await memory_client.distill_persona(
            user_id=user_id,
            character_id=request.character_id,
            force=request.force,
        )

        if not distill_response:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Memory service unavailable",
            )

        return PersonaDistillResponse(
            success=distill_response.get("success", False),
            persona=distill_response.get("persona"),
            facts_processed=distill_response.get("facts_processed", 0),
            episodes_processed=distill_response.get("episodes_processed", 0),
            token_count=distill_response.get("token_count", 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Persona distillation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Distillation failed: {str(e)}",
        )


@router.get("/persona/{character_id}", response_model=PersonaGetResponse)
async def get_persona(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Get distilled persona for a user-character pair.

    This endpoint:
    1. Verifies the user owns the character
    2. Retrieves the persona from the memory service
    3. Returns the persona profile if it exists
    """
    # Verify character ownership
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()

    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    # Get persona
    try:
        persona_payload = await memory_client.get_persona(
            user_id=user_id,
            character_id=character_id,
        )

        if persona_payload and persona_payload.get("exists"):
            return PersonaGetResponse(
                exists=True,
                persona=persona_payload.get("persona"),
                updated_at=persona_payload.get("updated_at"),
            )
        else:
            return PersonaGetResponse(
                exists=False,
                persona=None,
                updated_at=None,
            )

    except Exception as e:
        logger.error(f"Persona retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Persona retrieval failed: {str(e)}",
        )


@router.delete("/persona/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Delete persona for a user-character pair.

    This endpoint:
    1. Verifies the user owns the character
    2. Deletes the persona from the memory service
    """
    # Verify character ownership
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()

    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    # Delete persona
    try:
        success = await memory_client.delete_persona(
            user_id=user_id,
            character_id=character_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete persona",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Persona deletion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Persona deletion failed: {str(e)}",
        )
