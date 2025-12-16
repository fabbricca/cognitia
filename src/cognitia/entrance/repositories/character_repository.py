"""Character repository with access control queries."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from .base import BaseRepository
from ..database import Character, CharacterVoicePermission


class CharacterRepository(BaseRepository[Character]):
    """Repository for Character operations with access control."""

    async def get_user_characters(
        self,
        user_id: UUID,
        include_public: bool = False
    ) -> List[Character]:
        """Get characters owned by user, optionally including public ones."""
        query = select(Character)

        if include_public:
            query = query.where(
                or_(
                    Character.user_id == user_id,
                    Character.is_public == True
                )
            )
        else:
            query = query.where(Character.user_id == user_id)

        query = query.order_by(Character.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_public_characters(
        self,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Character]:
        """Get public characters with optional filters."""
        query = select(Character).where(Character.is_public == True)

        if tags:
            # PostgreSQL array overlap operator
            query = query.where(Character.tags.overlap(tags))

        if category:
            query = query.where(Character.category == category)

        query = query.order_by(Character.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def can_use_voice_model(
        self,
        character_id: UUID,
        user_id: UUID
    ) -> bool:
        """
        Check if user can use character's RVC voice model.

        Rules:
        - Character owner → always allowed
        - Public character → NOT allowed (prevents voice cloning)
        - Explicit permission → allowed
        """
        character = await self.get(character_id)
        if not character or not character.rvc_model_path:
            return False

        # Owner can always use
        if character.user_id == user_id:
            return True

        # Check explicit permission
        result = await self.session.execute(
            select(CharacterVoicePermission).where(
                and_(
                    CharacterVoicePermission.character_id == character_id,
                    CharacterVoicePermission.allowed_user_id == user_id
                )
            )
        )
        permission = result.scalar_one_or_none()
        return permission is not None

    async def grant_voice_permission(
        self,
        character_id: UUID,
        allowed_user_id: UUID
    ) -> CharacterVoicePermission:
        """Grant voice model usage permission to a user."""
        permission = CharacterVoicePermission(
            character_id=character_id,
            allowed_user_id=allowed_user_id
        )
        self.session.add(permission)
        await self.session.flush()
        await self.session.refresh(permission)
        return permission

    async def revoke_voice_permission(
        self,
        character_id: UUID,
        allowed_user_id: UUID
    ) -> bool:
        """Revoke voice model permission."""
        result = await self.session.execute(
            select(CharacterVoicePermission).where(
                and_(
                    CharacterVoicePermission.character_id == character_id,
                    CharacterVoicePermission.allowed_user_id == allowed_user_id
                )
            )
        )
        permission = result.scalar_one_or_none()
        if not permission:
            return False

        await self.session.delete(permission)
        await self.session.flush()
        return True
