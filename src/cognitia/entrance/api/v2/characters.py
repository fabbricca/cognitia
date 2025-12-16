"""Character API endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query

from ...dependencies import get_current_user, get_current_user_optional, get_character_service
from ...services import CharacterService
from ...schemas.character import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterWithVoiceResponse,
    VoicePermissionRequest,
)
from ...database import User
from ...core.exceptions import (
    ResourceNotFoundError,
    ResourceAccessDeniedError,
    VoicePermissionDeniedError,
)


router = APIRouter(prefix="/characters", tags=["Characters"])


@router.post("", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
async def create_character(
    character: CharacterCreate,
    current_user: User = Depends(get_current_user),
    character_service: CharacterService = Depends(get_character_service),
):
    """
    Create a new character.

    Character is owned by the authenticated user.
    """
    new_character = await character_service.create_character(
        user_id=current_user.id,
        **character.model_dump()
    )

    return CharacterResponse.model_validate(new_character)


@router.get("", response_model=List[CharacterResponse])
async def list_my_characters(
    current_user: User = Depends(get_current_user),
    character_service: CharacterService = Depends(get_character_service),
    include_public: bool = Query(False, description="Include public characters"),
):
    """
    List current user's characters.

    Optionally include public characters from marketplace.
    """
    characters = await character_service.get_user_characters(
        user_id=current_user.id,
        include_public=include_public
    )

    return [CharacterResponse.model_validate(c) for c in characters]


@router.get("/marketplace", response_model=List[CharacterResponse])
async def browse_marketplace(
    tags: Optional[List[str]] = Query(None, description="Filter by tags"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    Browse public character marketplace.

    No authentication required.
    """
    from ...dependencies import get_character_service
    from ...repositories import CharacterRepository
    from ...database import Character, async_session_maker

    async with async_session_maker() as session:
        char_repo = CharacterRepository(Character, session)
        char_service = CharacterService(char_repo)

        characters = await char_service.get_public_characters(
            tags=tags,
            category=category,
            limit=limit,
            offset=offset
        )

        return [CharacterResponse.model_validate(c) for c in characters]


@router.get("/{character_id}", response_model=CharacterWithVoiceResponse)
async def get_character(
    character_id: UUID,
    current_user: Optional[User] = Depends(get_current_user_optional),
    character_service: CharacterService = Depends(get_character_service),
):
    """
    Get character by ID.

    Public characters can be viewed without authentication.
    Private characters require ownership.
    """
    try:
        character = await character_service.get_character(
            character_id=character_id,
            requesting_user_id=current_user.id if current_user else None
        )

        # Check voice access if user is authenticated
        has_voice_access = False
        if current_user:
            has_voice_access = await character_service.check_voice_access(
                character_id=character_id,
                user_id=current_user.id
            )

        response = CharacterWithVoiceResponse.model_validate(character)
        response.has_voice_access = has_voice_access
        return response

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message
        )
    except ResourceAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message
        )


@router.patch("/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: UUID,
    updates: CharacterUpdate,
    current_user: User = Depends(get_current_user),
    character_service: CharacterService = Depends(get_character_service),
):
    """
    Update character.

    Only the character owner can update.
    """
    try:
        update_data = updates.model_dump(exclude_unset=True)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        updated_character = await character_service.update_character(
            character_id=character_id,
            user_id=current_user.id,
            **update_data
        )

        return CharacterResponse.model_validate(updated_character)

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message
        )
    except ResourceAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message
        )


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(
    character_id: UUID,
    current_user: User = Depends(get_current_user),
    character_service: CharacterService = Depends(get_character_service),
):
    """
    Delete character.

    Only the character owner can delete.
    All associated chats and messages will be deleted.
    """
    try:
        await character_service.delete_character(
            character_id=character_id,
            user_id=current_user.id
        )
        return None

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message
        )
    except ResourceAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message
        )


@router.post("/{character_id}/voice-permission", status_code=status.HTTP_201_CREATED)
async def grant_voice_permission(
    character_id: UUID,
    request: VoicePermissionRequest,
    current_user: User = Depends(get_current_user),
    character_service: CharacterService = Depends(get_character_service),
):
    """
    Grant voice model permission to another user.

    Only the character owner can grant voice permissions.
    This allows the specified user to use the character's RVC voice model.
    """
    try:
        await character_service.grant_voice_permission(
            character_id=character_id,
            owner_id=current_user.id,
            allowed_user_id=request.user_id
        )

        return {"message": "Voice permission granted"}

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message
        )
    except ResourceAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message
        )


@router.delete("/{character_id}/voice-permission/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_voice_permission(
    character_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    character_service: CharacterService = Depends(get_character_service),
):
    """
    Revoke voice model permission from a user.

    Only the character owner can revoke voice permissions.
    """
    try:
        revoked = await character_service.revoke_voice_permission(
            character_id=character_id,
            owner_id=current_user.id,
            allowed_user_id=user_id
        )

        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice permission not found"
            )

        return None

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message
        )
    except ResourceAccessDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.message
        )
