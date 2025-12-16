"""Character service with access control."""

from typing import List, Optional
from uuid import UUID

from ..repositories.character_repository import CharacterRepository
from ..core.exceptions import (
    ResourceNotFoundError,
    ResourceAccessDeniedError,
    VoicePermissionDeniedError,
)
from ..database import Character


class CharacterService:
    """Business logic for Character operations."""

    def __init__(self, character_repo: CharacterRepository):
        self.character_repo = character_repo

    async def create_character(
        self,
        user_id: UUID,
        name: str,
        description: Optional[str],
        system_prompt: str,
        persona_prompt: Optional[str] = None,
        voice_model: str = "af_bella",
        prompt_template: str = "pygmalion",
        is_public: bool = False,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        **kwargs
    ) -> Character:
        """Create new character."""
        return await self.character_repo.create(
            user_id=user_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            persona_prompt=persona_prompt,
            voice_model=voice_model,
            prompt_template=prompt_template,
            is_public=is_public,
            tags=tags,
            category=category,
            **kwargs
        )

    async def get_character(
        self,
        character_id: UUID,
        requesting_user_id: Optional[UUID] = None
    ) -> Character:
        """Get character by ID with access control."""
        character = await self.character_repo.get(character_id)

        if not character:
            raise ResourceNotFoundError("Character", str(character_id))

        # Check access: owner or public character
        if requesting_user_id:
            if character.user_id != requesting_user_id and not character.is_public:
                raise ResourceAccessDeniedError(
                    "You don't have permission to view this character"
                )

        return character

    async def update_character(
        self,
        character_id: UUID,
        user_id: UUID,
        **updates
    ) -> Character:
        """Update character (owner only)."""
        character = await self.character_repo.get(character_id)

        if not character:
            raise ResourceNotFoundError("Character", str(character_id))

        # Only owner can update
        if character.user_id != user_id:
            raise ResourceAccessDeniedError(
                "Only the character owner can update it"
            )

        return await self.character_repo.update(character_id, **updates)

    async def delete_character(
        self,
        character_id: UUID,
        user_id: UUID
    ) -> bool:
        """Delete character (owner only)."""
        character = await self.character_repo.get(character_id)

        if not character:
            raise ResourceNotFoundError("Character", str(character_id))

        # Only owner can delete
        if character.user_id != user_id:
            raise ResourceAccessDeniedError(
                "Only the character owner can delete it"
            )

        return await self.character_repo.delete(character_id)

    async def get_user_characters(
        self,
        user_id: UUID,
        include_public: bool = False
    ) -> List[Character]:
        """Get all characters for a user."""
        return await self.character_repo.get_user_characters(
            user_id=user_id,
            include_public=include_public
        )

    async def get_public_characters(
        self,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Character]:
        """Browse public character marketplace."""
        return await self.character_repo.get_public_characters(
            tags=tags,
            category=category,
            limit=limit,
            offset=offset,
        )

    async def check_voice_access(
        self,
        character_id: UUID,
        user_id: UUID
    ) -> bool:
        """Check if user can use character's RVC voice model."""
        return await self.character_repo.can_use_voice_model(
            character_id=character_id,
            user_id=user_id
        )

    async def grant_voice_permission(
        self,
        character_id: UUID,
        owner_id: UUID,
        allowed_user_id: UUID
    ) -> None:
        """Grant voice model permission (owner only)."""
        character = await self.character_repo.get(character_id)

        if not character:
            raise ResourceNotFoundError("Character", str(character_id))

        if character.user_id != owner_id:
            raise ResourceAccessDeniedError(
                "Only the character owner can grant voice permissions"
            )

        await self.character_repo.grant_voice_permission(
            character_id=character_id,
            allowed_user_id=allowed_user_id
        )

    async def revoke_voice_permission(
        self,
        character_id: UUID,
        owner_id: UUID,
        allowed_user_id: UUID
    ) -> bool:
        """Revoke voice model permission (owner only)."""
        character = await self.character_repo.get(character_id)

        if not character:
            raise ResourceNotFoundError("Character", str(character_id))

        if character.user_id != owner_id:
            raise ResourceAccessDeniedError(
                "Only the character owner can revoke voice permissions"
            )

        return await self.character_repo.revoke_voice_permission(
            character_id=character_id,
            allowed_user_id=allowed_user_id
        )
