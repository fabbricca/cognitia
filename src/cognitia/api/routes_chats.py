"""Chat router: CRUD operations for chat sessions and messages."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .auth import get_user_id
from .cache import cache
from .database import Character, Chat, Message, get_session
from .schemas import (
    ChatCreate,
    ChatListResponse,
    ChatResponse,
    MessageCreate,
    MessageListResponse,
    MessageResponse,
)

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("/", response_model=ChatListResponse)
async def list_chats(
    character_id: UUID = Query(None, description="Filter by character"),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """List chats, optionally filtered by character."""
    # Build query - join through character to verify ownership
    query = (
        select(Chat)
        .join(Character)
        .where(Character.user_id == user_id)
        .order_by(Chat.updated_at.desc())
    )
    
    if character_id:
        query = query.where(Chat.character_id == character_id)
    
    result = await session.execute(query)
    chats = result.scalars().all()
    
    return ChatListResponse(
        chats=[ChatResponse.model_validate(c) for c in chats]
    )


@router.post("/", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    data: ChatCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Create a new chat session."""
    # Verify character belongs to user
    result = await session.execute(
        select(Character).where(
            Character.id == data.character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()
    
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    chat = Chat(
        character_id=data.character_id,
        title=data.title or f"Chat with {character.name}",
    )
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    
    return ChatResponse.model_validate(chat)


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Get a specific chat."""
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(
            Chat.id == chat_id,
            Character.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()
    
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    return ChatResponse.model_validate(chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Delete a chat and all its messages."""
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(
            Chat.id == chat_id,
            Character.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()
    
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    await session.delete(chat)
    await session.commit()


@router.get("/{chat_id}/messages", response_model=MessageListResponse)
async def get_messages(
    chat_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Get messages for a chat with pagination."""
    # Try cache first for recent messages (offset=0)
    if offset == 0:
        cached_messages = await cache.get_recent_messages(str(chat_id))
        if cached_messages:
            # Still need to verify ownership
            result = await session.execute(
                select(Chat)
                .join(Character)
                .where(
                    Chat.id == chat_id,
                    Character.user_id == user_id,
                )
            )
            if result.scalar_one_or_none():
                return MessageListResponse(
                    messages=[MessageResponse.model_validate(m) for m in cached_messages[-limit:]],
                    has_more=len(cached_messages) > limit,
                )
    
    # Verify chat ownership
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(
            Chat.id == chat_id,
            Character.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()
    
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    # Get messages with pagination
    result = await session.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit + 1)  # Fetch one extra to check if there's more
    )
    messages = result.scalars().all()
    
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:-1]
    
    # Reverse to get chronological order
    messages = list(reversed(messages))
    
    # Cache the messages if this is the first page
    if offset == 0:
        await cache.set_recent_messages(
            str(chat_id),
            [m.__dict__ for m in messages]
        )
    
    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        has_more=has_more,
    )


@router.post("/{chat_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    chat_id: UUID,
    data: MessageCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Add a message to a chat (used for persistence, not real-time sending)."""
    # Verify chat ownership
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(
            Chat.id == chat_id,
            Character.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()
    
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    message = Message(
        chat_id=chat_id,
        role=data.role,
        content=data.content,
        audio_url=data.audio_url,
    )
    session.add(message)
    
    # Update chat's updated_at
    from datetime import datetime
    chat.updated_at = datetime.utcnow()
    
    await session.commit()
    await session.refresh(message)
    
    # Add to cache
    await cache.append_message(str(chat_id), {
        "id": str(message.id),
        "chat_id": str(message.chat_id),
        "role": message.role,
        "content": message.content,
        "audio_url": message.audio_url,
        "created_at": message.created_at.isoformat(),
    })
    
    return MessageResponse.model_validate(message)
