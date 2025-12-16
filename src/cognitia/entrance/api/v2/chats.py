"""Chat management API endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...dependencies import (
    get_chat_repository,
    get_character_repository,
    get_message_repository,
    get_current_user,
)
from ...repositories import ChatRepository, CharacterRepository, MessageRepository
from ...schemas.chat import (
    ChatCreate,
    ChatUpdate,
    ChatResponse,
    ChatDetailResponse,
    ChatParticipantResponse,
    ChatCharacterResponse,
    AddParticipantRequest,
    AddCharacterRequest,
    MessageResponse,
    MessageListResponse,
    SendMessageRequest,
)
from ...database import User, Chat


router = APIRouter(prefix="/chats", tags=["Chats"])


@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    request: ChatCreate,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    """
    Create a new chat.

    Creates a chat and adds the creator as owner. Optionally adds characters and participants.
    """
    # Create the chat
    chat = await chat_repo.create(
        title=request.title or "New Chat",
    )

    # Add creator as owner
    await chat_repo.add_participant(
        chat_id=chat.id,
        user_id=current_user.id,
        role="owner",
    )

    # Add characters if specified
    for char_id in request.character_ids:
        # Verify character exists and user has access
        character = await character_repo.get(char_id)
        if not character:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character {char_id} not found"
            )

        # Check if character is public or owned by user
        if not character.is_public and character.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No access to character {char_id}"
            )

        await chat_repo.add_character(
            chat_id=chat.id,
            character_id=char_id,
            added_by_user_id=current_user.id,
        )

    # Add participant users if specified
    for user_id in request.participant_user_ids:
        if user_id != current_user.id:  # Don't add creator again
            await chat_repo.add_participant(
                chat_id=chat.id,
                user_id=user_id,
                role="member",
            )

    return ChatResponse.model_validate(chat)


@router.get("", response_model=List[ChatResponse])
async def list_chats(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
):
    """
    List all chats for the current user.

    Returns chats where the user is a participant, ordered by most recent activity.
    """
    chats = await chat_repo.get_user_chats(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    # Add unread count for each chat
    chat_responses = []
    for chat in chats:
        unread_count = await chat_repo.count_unread_messages(chat.id, current_user.id)
        chat_response = ChatResponse.model_validate(chat)
        chat_response.unread_count = unread_count
        chat_responses.append(chat_response)

    return chat_responses


@router.get("/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(
    chat_id: UUID,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
):
    """
    Get chat details including participants and characters.

    Returns detailed information about a specific chat.
    """
    # Verify access
    if not await chat_repo.is_participant(chat_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a participant in this chat"
        )

    chat = await chat_repo.get(chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )

    # Get participants
    participants = await chat_repo.get_participants(chat_id)
    participant_responses = []
    for participant in participants:
        # Get role and timestamps
        from ...database import ChatParticipant
        from sqlalchemy import select, and_

        result = await chat_repo.session.execute(
            select(ChatParticipant).where(
                and_(
                    ChatParticipant.chat_id == chat_id,
                    ChatParticipant.user_id == participant.id,
                )
            )
        )
        chat_participant = result.scalar_one()

        participant_responses.append(ChatParticipantResponse(
            user_id=participant.id,
            role=chat_participant.role,
            joined_at=chat_participant.joined_at,
            last_read_at=chat_participant.last_read_at,
        ))

    # Get characters
    characters = await chat_repo.get_characters(chat_id)
    character_responses = []
    for character in characters:
        from ...database import ChatCharacter
        from sqlalchemy import select, and_

        result = await chat_repo.session.execute(
            select(ChatCharacter).where(
                and_(
                    ChatCharacter.chat_id == chat_id,
                    ChatCharacter.character_id == character.id,
                )
            )
        )
        chat_character = result.scalar_one()

        character_responses.append(ChatCharacterResponse(
            character_id=character.id,
            character_name=character.name,
            added_at=chat_character.added_at,
        ))

    return ChatDetailResponse(
        id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        participants=participant_responses,
        characters=character_responses,
    )


@router.patch("/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: UUID,
    request: ChatUpdate,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
):
    """
    Update chat details.

    Only chat owner or admin can update the chat.
    """
    # Verify access
    role = await chat_repo.get_participant_role(chat_id, current_user.id)
    if role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner or admin can update chat"
        )

    chat = await chat_repo.get(chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )

    # Update fields
    update_data = request.model_dump(exclude_unset=True)
    await chat_repo.update(chat_id, **update_data)

    updated_chat = await chat_repo.get(chat_id)
    return ChatResponse.model_validate(updated_chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: UUID,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
):
    """
    Delete a chat.

    Only the chat owner can delete the chat.
    """
    # Verify access
    role = await chat_repo.get_participant_role(chat_id, current_user.id)
    if role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner can delete chat"
        )

    chat = await chat_repo.get(chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )

    await chat_repo.delete(chat_id)


@router.post("/{chat_id}/participants", response_model=ChatParticipantResponse)
async def add_participant(
    chat_id: UUID,
    request: AddParticipantRequest,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
):
    """
    Add a participant to the chat.

    Only chat owner or admin can add participants.
    """
    # Verify access
    role = await chat_repo.get_participant_role(chat_id, current_user.id)
    if role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner or admin can add participants"
        )

    # Add participant
    participant = await chat_repo.add_participant(
        chat_id=chat_id,
        user_id=request.user_id,
        role=request.role,
    )

    return ChatParticipantResponse(
        user_id=participant.user_id,
        role=participant.role,
        joined_at=participant.joined_at,
        last_read_at=participant.last_read_at,
    )


@router.delete("/{chat_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(
    chat_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
):
    """
    Remove a participant from the chat.

    Owner/admin can remove others. Users can remove themselves (leave chat).
    """
    # Check if user is removing themselves
    if user_id == current_user.id:
        # User can leave chat
        removed = await chat_repo.remove_participant(chat_id, user_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not a participant in this chat"
            )
        return

    # Check if user has permission to remove others
    role = await chat_repo.get_participant_role(chat_id, current_user.id)
    if role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner or admin can remove participants"
        )

    removed = await chat_repo.remove_participant(chat_id, user_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not a participant in this chat"
        )


@router.post("/{chat_id}/characters", response_model=ChatCharacterResponse)
async def add_character(
    chat_id: UUID,
    request: AddCharacterRequest,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    """
    Add a character to the chat.

    Only chat participants can add characters they have access to.
    """
    # Verify user is participant
    if not await chat_repo.is_participant(chat_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a participant in this chat"
        )

    # Verify character exists and user has access
    character = await character_repo.get(request.character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )

    if not character.is_public and character.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this character"
        )

    # Add character
    chat_character = await chat_repo.add_character(
        chat_id=chat_id,
        character_id=request.character_id,
        added_by_user_id=current_user.id,
    )

    return ChatCharacterResponse(
        character_id=chat_character.character_id,
        character_name=character.name,
        added_at=chat_character.added_at,
    )


@router.delete("/{chat_id}/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_character(
    chat_id: UUID,
    character_id: UUID,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
):
    """
    Remove a character from the chat.

    Only chat owner or admin can remove characters.
    """
    # Verify access
    role = await chat_repo.get_participant_role(chat_id, current_user.id)
    if role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner or admin can remove characters"
        )

    removed = await chat_repo.remove_character(chat_id, character_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not in this chat"
        )


@router.get("/{chat_id}/messages", response_model=MessageListResponse)
async def list_messages(
    chat_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
    message_repo: MessageRepository = Depends(get_message_repository),
):
    """
    List messages in a chat.

    Returns messages in chronological order (oldest first).
    """
    # Verify access
    if not await chat_repo.is_participant(chat_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a participant in this chat"
        )

    messages = await message_repo.get_chat_messages(
        chat_id=chat_id,
        limit=limit,
    )

    total_count = await message_repo.count_chat_messages(chat_id)
    has_more = len(messages) >= limit

    # Update last read timestamp
    await chat_repo.update_last_read(chat_id, current_user.id)

    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        total_count=total_count,
        has_more=has_more,
    )


@router.post("/{chat_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    chat_id: UUID,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    chat_repo: ChatRepository = Depends(get_chat_repository),
    message_repo: MessageRepository = Depends(get_message_repository),
):
    """
    Send a message in a chat.

    Creates a user message in the chat. In Phase 4, this will trigger AI response via Celery.
    """
    # Verify access
    if not await chat_repo.is_participant(chat_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a participant in this chat"
        )

    # Create message
    message = await message_repo.create(
        chat_id=chat_id,
        role="user",
        content=request.content,
    )

    # Queue AI response generation (background task)
    if request.character_id:
        from ...tasks import generate_ai_response
        generate_ai_response.delay(
            chat_id=str(chat_id),
            message_id=str(message.id),
            character_id=str(request.character_id),
            user_message=request.content
        )

    # Update last read timestamp
    await chat_repo.update_last_read(chat_id, current_user.id)

    return MessageResponse.model_validate(message)
