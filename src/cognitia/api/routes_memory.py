"""Memory router: endpoints for memory retrieval and persona management."""

from typing import Optional
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
        persona = await memory_client.get_persona(
            user_id=user_id,
            character_id=character_id,
        )

        if persona:
            return PersonaGetResponse(
                exists=True,
                persona=persona,
                updated_at=None,  # TODO: Get from memory service response
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
