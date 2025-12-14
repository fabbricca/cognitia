"""Database models and connection for Cognitia Entrance."""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, AsyncGenerator
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    CHAR,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# Database URL from environment or default to SQLite for development
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./data/cognitia.db"
)

# Check if using PostgreSQL
IS_POSTGRES = DATABASE_URL.startswith("postgresql")


class GUID(TypeDecorator):
    """Platform-independent GUID type.
    
    Uses PostgreSQL's UUID type when available, otherwise uses CHAR(36).
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(GUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is not None:
            if dialect.name == 'postgresql':
                return value
            else:
                if isinstance(value, UUID):
                    return str(value)
                return value
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if not isinstance(value, UUID):
                return UUID(value)
        return value


# Create async engine
if DATABASE_URL.startswith("sqlite"):
    engine = create_async_engine(DATABASE_URL, echo=False)
else:
    engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# Session factory
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Subscription-related fields
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    referral_code: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True)
    referred_by: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    characters: Mapped[list["Character"]] = relationship(
        "Character", back_populates="user", cascade="all, delete-orphan"
    )
    subscription: Mapped[Optional["UserSubscription"]] = relationship(
        "UserSubscription", back_populates="user", uselist=False
    )


class Character(Base):
    """AI Character/Persona model."""
    
    __tablename__ = "characters"
    
    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Persona/lorebook - detailed character biography (separate from system instructions)
    persona_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_model: Mapped[str] = mapped_column(
        String(100), default="af_bella", nullable=False
    )
    rvc_model_path: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    rvc_index_path: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="characters")
    chats: Mapped[list["Chat"]] = relationship(
        "Chat", back_populates="character", cascade="all, delete-orphan"
    )


class Chat(Base):
    """Chat session model."""
    
    __tablename__ = "chats"
    
    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    character_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("characters.id", ondelete="CASCADE")
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    # Relationships
    character: Mapped["Character"] = relationship("Character", back_populates="chats")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="chat", cascade="all, delete-orphan",
        order_by="Message.created_at"
    )


class Message(Base):
    """Chat message model."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    chat_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("chats.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    audio_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # Relationships
    chat: Mapped["Chat"] = relationship("Chat", back_populates="messages")


class SubscriptionPlan(Base):
    """Subscription plan/tier model."""

    __tablename__ = "subscription_plans"

    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    price_monthly: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    price_yearly: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    # Feature Limits
    max_characters: Mapped[int] = mapped_column(Integer, nullable=False)
    max_messages_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    max_audio_minutes_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    max_voice_clones: Mapped[int] = mapped_column(Integer, nullable=False)

    # Advanced Features (boolean flags)
    can_use_custom_voices: Mapped[bool] = mapped_column(Boolean, default=False)
    can_use_phone_calls: Mapped[bool] = mapped_column(Boolean, default=False)
    can_access_premium_models: Mapped[bool] = mapped_column(Boolean, default=False)
    can_export_conversations: Mapped[bool] = mapped_column(Boolean, default=False)
    priority_processing: Mapped[bool] = mapped_column(Boolean, default=False)

    # Model Access (using Text for SQLite compatibility, will work as array in PostgreSQL)
    allowed_llm_models: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allowed_tts_voices: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_context_messages: Mapped[int] = mapped_column(Integer, default=10)

    # API & Integrations
    api_access: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_support: Mapped[bool] = mapped_column(Boolean, default=False)

    # Metadata
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription", back_populates="plan"
    )


class UserSubscription(Base):
    """User's active subscription."""

    __tablename__ = "user_subscriptions"

    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("subscription_plans.id"), nullable=False
    )

    # Subscription Status
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    # Billing Cycle
    current_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)

    # Payment Provider (Stripe, Paddle, etc.)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Trial Period
    trial_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trial_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscription")
    plan: Mapped["SubscriptionPlan"] = relationship("SubscriptionPlan", back_populates="subscriptions")


class DailyUsageCache(Base):
    """Cache for fast daily usage lookups (rate limiting)."""

    __tablename__ = "daily_usage_cache"

    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )
    date: Mapped[datetime] = mapped_column(Date, primary_key=True)

    # Counters
    messages_count: Mapped[int] = mapped_column(Integer, default=0)
    audio_minutes: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class UsageRecord(Base):
    """Detailed usage record for analytics and billing."""

    __tablename__ = "usage_records"

    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Usage Type
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Metrics
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    audio_duration_seconds: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    # Context
    character_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("characters.id", ondelete="SET NULL"), nullable=True
    )
    chat_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True
    )

    # Cost Tracking (for internal analytics)
    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaymentTransaction(Base):
    """Payment transaction record."""

    __tablename__ = "payment_transactions"

    id: Mapped[UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("user_subscriptions.id"), nullable=True
    )

    # Transaction Details
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Payment Provider
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Metadata
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session as async context manager."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session_dep() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for FastAPI dependency injection."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
