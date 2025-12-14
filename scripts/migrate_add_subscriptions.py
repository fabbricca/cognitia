#!/usr/bin/env python3
"""
Database migration script to add subscription management tables.
This script adds:
- subscription_plans
- user_subscriptions
- daily_usage_cache
- usage_records
- payment_transactions
- feature_flags
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text
from cognitia.entrance.database import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    """Run the migration"""

    async with engine.begin() as conn:
        logger.info("Starting subscription system migration...")

        # Create subscription_plans table
        logger.info("Creating subscription_plans table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS subscription_plans (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(50) NOT NULL UNIQUE,
                display_name VARCHAR(100) NOT NULL,
                price_monthly DECIMAL(10,2) NOT NULL,
                price_yearly DECIMAL(10,2),

                -- Feature Limits
                max_characters INTEGER NOT NULL,
                max_messages_per_day INTEGER NOT NULL,
                max_audio_minutes_per_day INTEGER NOT NULL,
                max_voice_clones INTEGER NOT NULL,

                -- Advanced Features (boolean flags)
                can_use_custom_voices BOOLEAN DEFAULT false,
                can_use_phone_calls BOOLEAN DEFAULT false,
                can_access_premium_models BOOLEAN DEFAULT false,
                can_export_conversations BOOLEAN DEFAULT false,
                priority_processing BOOLEAN DEFAULT false,

                -- Model Access
                allowed_llm_models TEXT[],
                allowed_tts_voices TEXT[],
                max_context_messages INTEGER DEFAULT 10,

                -- API & Integrations
                api_access BOOLEAN DEFAULT false,
                webhook_support BOOLEAN DEFAULT false,

                -- Metadata
                is_active BOOLEAN DEFAULT true,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        # Create user_subscriptions table
        logger.info("Creating user_subscriptions table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id UUID NOT NULL REFERENCES subscription_plans(id),

                -- Subscription Status
                status VARCHAR(20) NOT NULL DEFAULT 'active',

                -- Billing Cycle
                current_period_start TIMESTAMPTZ NOT NULL,
                current_period_end TIMESTAMPTZ NOT NULL,
                cancel_at_period_end BOOLEAN DEFAULT false,

                -- Payment Provider (Stripe, Paddle, etc.)
                stripe_subscription_id VARCHAR(255),
                stripe_customer_id VARCHAR(255),
                payment_method VARCHAR(50),

                -- Trial Period
                trial_start TIMESTAMPTZ,
                trial_end TIMESTAMPTZ,

                -- Metadata
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),

                UNIQUE(user_id)
            )
        """))

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user
            ON user_subscriptions(user_id)
        """))

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_user_subscriptions_status
            ON user_subscriptions(status)
        """))

        # Create usage_records table
        logger.info("Creating usage_records table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usage_records (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

                -- Usage Type
                resource_type VARCHAR(50) NOT NULL,

                -- Metrics
                quantity INTEGER DEFAULT 1,
                tokens_used INTEGER,
                audio_duration_seconds DECIMAL(10,2),

                -- Context
                character_id UUID REFERENCES characters(id) ON DELETE SET NULL,
                chat_id UUID REFERENCES chats(id) ON DELETE SET NULL,

                -- Cost Tracking (for internal analytics)
                estimated_cost_usd DECIMAL(10,6),

                -- Timestamp
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_usage_records_user_date
            ON usage_records(user_id, created_at)
        """))

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_usage_records_type
            ON usage_records(resource_type)
        """))

        # Create daily_usage_cache table
        logger.info("Creating daily_usage_cache table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_usage_cache (
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date DATE NOT NULL,

                -- Counters
                messages_count INTEGER DEFAULT 0,
                audio_minutes DECIMAL(10,2) DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,

                -- Metadata
                updated_at TIMESTAMPTZ DEFAULT NOW(),

                PRIMARY KEY (user_id, date)
            )
        """))

        # Create payment_transactions table
        logger.info("Creating payment_transactions table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS payment_transactions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                subscription_id UUID REFERENCES user_subscriptions(id),

                -- Transaction Details
                amount DECIMAL(10,2) NOT NULL,
                currency VARCHAR(3) DEFAULT 'USD',
                status VARCHAR(20) NOT NULL,

                -- Payment Provider
                provider VARCHAR(50) NOT NULL,
                provider_transaction_id VARCHAR(255),

                -- Metadata
                description TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_payment_transactions_user
            ON payment_transactions(user_id)
        """))

        # Create feature_flags table
        logger.info("Creating feature_flags table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS feature_flags (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(100) NOT NULL UNIQUE,
                description TEXT,
                is_enabled BOOLEAN DEFAULT false,

                -- Targeting
                enabled_for_plans UUID[],
                enabled_for_users UUID[],
                rollout_percentage INTEGER DEFAULT 0,

                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        # Add columns to existing users table
        logger.info("Adding new columns to users table...")
        try:
            await conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT false,
                ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS referral_code VARCHAR(20) UNIQUE,
                ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES users(id)
            """))
        except Exception as e:
            logger.warning(f"Could not add columns to users table (may already exist): {e}")

        # Seed default subscription plans
        logger.info("Seeding default subscription plans...")
        await conn.execute(text("""
            INSERT INTO subscription_plans
            (name, display_name, price_monthly, price_yearly, max_characters,
             max_messages_per_day, max_audio_minutes_per_day, max_voice_clones,
             allowed_llm_models, allowed_tts_voices, max_context_messages,
             can_use_custom_voices, can_use_phone_calls, api_access, sort_order)
            VALUES
            ('free', 'Free Tier', 0.00, 0.00, 3, 50, 10, 0,
             ARRAY['hermes-4-7b'], ARRAY['af_bella', 'am_adam', 'bf_emma'], 10,
             false, false, false, 1),

            ('basic', 'Basic Plan', 9.99, 99.99, 10, 500, 60, 1,
             ARRAY['hermes-4-14b'], ARRAY['af_bella', 'af_nicole', 'am_adam', 'am_michael',
                                           'bf_emma', 'bf_isabella', 'bm_george', 'bm_lewis',
                                           'af_alloy', 'af_nova'], 50,
             true, false, false, 2),

            ('pro', 'Pro Plan', 24.99, 249.99, 9999, 5000, 300, 5,
             ARRAY['hermes-4-14b', 'llama-3.3-70b'], ARRAY['*'], 200,
             true, true, true, 3),

            ('enterprise', 'Enterprise', 0.00, NULL, 9999, 999999, 999999, 9999,
             ARRAY['*'], ARRAY['*'], 9999,
             true, true, true, 4)
            ON CONFLICT (name) DO NOTHING
        """))

        # Update pro and enterprise plans with additional features
        logger.info("Updating plan features...")
        await conn.execute(text("""
            UPDATE subscription_plans SET
                can_access_premium_models = true,
                can_export_conversations = true,
                priority_processing = true,
                webhook_support = true
            WHERE name IN ('pro', 'enterprise')
        """))

        # Create free subscriptions for all existing users
        logger.info("Creating free subscriptions for existing users...")
        await conn.execute(text("""
            INSERT INTO user_subscriptions (user_id, plan_id, status, current_period_start, current_period_end)
            SELECT
                u.id,
                p.id,
                'active',
                NOW(),
                NOW() + INTERVAL '100 years'
            FROM users u
            CROSS JOIN subscription_plans p
            WHERE p.name = 'free'
            AND NOT EXISTS (SELECT 1 FROM user_subscriptions WHERE user_id = u.id)
        """))

        logger.info("✓ Migration completed successfully!")
        logger.info("\nCreated tables:")
        logger.info("  - subscription_plans")
        logger.info("  - user_subscriptions")
        logger.info("  - usage_records")
        logger.info("  - daily_usage_cache")
        logger.info("  - payment_transactions")
        logger.info("  - feature_flags")
        logger.info("\nSeeded 4 subscription plans: free, basic, pro, enterprise")
        logger.info("All existing users have been assigned to the free tier")


async def rollback():
    """Rollback the migration (drop all new tables)"""
    async with engine.begin() as conn:
        logger.warning("Rolling back subscription system migration...")

        await conn.execute(text("DROP TABLE IF EXISTS feature_flags CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS payment_transactions CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS daily_usage_cache CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS usage_records CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS user_subscriptions CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS subscription_plans CASCADE"))

        # Remove added columns from users table
        try:
            await conn.execute(text("""
                ALTER TABLE users
                DROP COLUMN IF EXISTS onboarding_completed,
                DROP COLUMN IF EXISTS last_active_at,
                DROP COLUMN IF EXISTS referral_code,
                DROP COLUMN IF EXISTS referred_by
            """))
        except Exception as e:
            logger.warning(f"Could not remove columns from users table: {e}")

        logger.info("✓ Rollback completed")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        print("⚠️  WARNING: This will delete all subscription data!")
        confirm = input("Type 'yes' to confirm rollback: ")
        if confirm.lower() == 'yes':
            asyncio.run(rollback())
        else:
            print("Rollback cancelled")
    else:
        asyncio.run(migrate())
