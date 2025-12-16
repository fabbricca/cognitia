"""Dependency injection for FastAPI endpoints."""

from typing import AsyncGenerator, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from .database import async_session_maker, User, Character, Chat, Message
from .repositories import (
    UserRepository,
    CharacterRepository,
    ChatRepository,
    MessageRepository,
    SubscriptionRepository,
    SubscriptionPlanRepository,
    EmailVerificationRepository,
    PasswordResetRepository,
)
from .services import AuthService, CharacterService
from .core.security import verify_jwt_token, TokenPayload
from .core.exceptions import UnauthorizedError


# Security scheme
security = HTTPBearer()


# Database session dependency
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Repository dependencies
async def get_user_repository(
    session: AsyncSession = Depends(get_session)
) -> UserRepository:
    """Get UserRepository instance."""
    return UserRepository(User, session)


async def get_character_repository(
    session: AsyncSession = Depends(get_session)
) -> CharacterRepository:
    """Get CharacterRepository instance."""
    return CharacterRepository(Character, session)


async def get_chat_repository(
    session: AsyncSession = Depends(get_session)
) -> ChatRepository:
    """Get ChatRepository instance."""
    return ChatRepository(Chat, session)


async def get_message_repository(
    session: AsyncSession = Depends(get_session)
) -> MessageRepository:
    """Get MessageRepository instance."""
    return MessageRepository(Message, session)


async def get_subscription_repository(
    session: AsyncSession = Depends(get_session)
) -> SubscriptionRepository:
    """Get SubscriptionRepository instance."""
    from .database import UserSubscription
    return SubscriptionRepository(UserSubscription, session)


async def get_subscription_plan_repository(
    session: AsyncSession = Depends(get_session)
) -> SubscriptionPlanRepository:
    """Get SubscriptionPlanRepository instance."""
    from .database import SubscriptionPlan
    return SubscriptionPlanRepository(SubscriptionPlan, session)


async def get_email_verification_repository(
    session: AsyncSession = Depends(get_session)
) -> EmailVerificationRepository:
    """Get EmailVerificationRepository instance."""
    from .database import EmailVerification
    return EmailVerificationRepository(EmailVerification, session)


async def get_password_reset_repository(
    session: AsyncSession = Depends(get_session)
) -> PasswordResetRepository:
    """Get PasswordResetRepository instance."""
    from .database import PasswordReset
    return PasswordResetRepository(PasswordReset, session)


# Service dependencies
async def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
    email_verification_repo: EmailVerificationRepository = Depends(get_email_verification_repository),
    password_reset_repo: PasswordResetRepository = Depends(get_password_reset_repository),
) -> AuthService:
    """Get AuthService instance."""
    return AuthService(user_repo, email_verification_repo, password_reset_repo)


async def get_character_service(
    character_repo: CharacterRepository = Depends(get_character_repository),
) -> CharacterService:
    """Get CharacterService instance."""
    return CharacterService(character_repo)


# Authentication dependencies
async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> TokenPayload:
    """
    Get current user from JWT token.

    Raises:
        HTTPException: If token is invalid or expired
    """
    token = credentials.credentials
    payload = verify_jwt_token(token, expected_type="access")

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user(
    payload: TokenPayload = Depends(get_current_user_payload),
    user_repo: UserRepository = Depends(get_user_repository),
) -> User:
    """
    Get current authenticated user.

    Raises:
        HTTPException: If user not found
    """
    user = await user_repo.get(UUID(payload.sub))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_admin_user(
    user: User = Depends(get_current_user)
) -> User:
    """
    Get current user and verify admin role.

    Raises:
        HTTPException: If user is not admin
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    return user


# Optional authentication (for public endpoints that enhance with auth)
async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Optional[User]:
    """
    Get current user if authenticated, None otherwise.

    Used for endpoints that work both authenticated and unauthenticated.
    """
    if not credentials:
        return None

    try:
        token = credentials.credentials
        payload = verify_jwt_token(token, expected_type="access")

        if not payload:
            return None

        user = await user_repo.get(UUID(payload.sub))
        return user
    except Exception:
        return None
