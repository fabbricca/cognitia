#!/usr/bin/env python3
"""Test script for Phase 2 repositories and services - run inside Docker container."""

import asyncio
import os
import sys
from uuid import uuid4

# Ensure we're using the container's environment
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://cognitia:dev_password@postgres:5432/cognitia")

# Add the src/cognitia/entrance directory to Python path to avoid parent __init__.py
sys.path.insert(0, "/app/src/cognitia/entrance")


async def test_security():
    """Test security utilities."""
    print("\n🔐 Testing Security Utilities")
    print("=" * 60)

    from core.security import (
        hash_password,
        verify_password,
        create_jwt_token,
        decode_jwt_token,
    )

    # Test password hashing
    password = "test_password_123"
    hashed = hash_password(password)
    print(f"✅ Password hashed successfully")

    # Test password verification
    is_valid = verify_password(password, hashed)
    assert is_valid is True, "Valid password verification failed"
    print(f"✅ Password verification passed")

    is_invalid = verify_password("wrong_password", hashed)
    assert is_invalid is False, "Invalid password incorrectly accepted"
    print(f"✅ Invalid password correctly rejected")

    # Test JWT token creation
    user_id = uuid4()
    token = create_jwt_token(
        user_id=user_id,
        email="test@example.com",
        role="user",
        token_type="access",
        expires_minutes=60,
    )
    print(f"✅ JWT token created")

    # Test JWT token decoding
    payload = decode_jwt_token(token)
    assert payload.sub == str(user_id), "User ID mismatch"
    assert payload.email == "test@example.com", "Email mismatch"
    assert payload.role == "user", "Role mismatch"
    assert payload.type == "access", "Token type mismatch"
    print(f"✅ JWT token decoded and verified")

    print("\n✅ All security tests passed!\n")


async def test_repositories():
    """Test repository layer."""
    print("\n📦 Testing Repository Layer")
    print("=" * 60)

    from database import async_session_maker, User, Character
    from repositories import (
        UserRepository,
        CharacterRepository,
    )

    async with async_session_maker() as session:
        # Initialize repositories
        user_repo = UserRepository(User, session)
        char_repo = CharacterRepository(Character, session)

        print("\n1️⃣ Testing UserRepository")
        print("-" * 60)

        # Create test user
        test_user = await user_repo.create(
            email=f"test_{uuid4().hex[:8]}@example.com",
            password_hash="hashed_password_123",
            first_name="Test",
            last_name="User",
            role="user",
            email_verified=False,
        )
        print(f"✅ Created user: {test_user.email}")
        print(f"   ID: {test_user.id}")
        print(f"   Name: {test_user.first_name} {test_user.last_name}")
        print(f"   Email verified: {test_user.email_verified}")

        # Test get_by_email
        found_user = await user_repo.get_by_email(test_user.email)
        assert found_user.id == test_user.id, "User not found by email"
        print(f"✅ Retrieved user by email")

        # Test email_exists
        exists = await user_repo.email_exists(test_user.email)
        assert exists is True, "Email exists check failed"
        print(f"✅ Email exists check passed")

        # Test update
        updated_user = await user_repo.update(
            test_user.id,
            email_verified=True,
            first_name="Updated"
        )
        assert updated_user.email_verified is True, "Email verification update failed"
        assert updated_user.first_name == "Updated", "Name update failed"
        print(f"✅ Updated user: email_verified={updated_user.email_verified}, first_name={updated_user.first_name}")

        print("\n2️⃣ Testing CharacterRepository")
        print("-" * 60)

        # Create test character
        test_char = await char_repo.create(
            user_id=test_user.id,
            name="Test Character",
            description="A test character for v2 repository testing",
            system_prompt="You are a helpful test character.",
            voice_model="af_bella",
            prompt_template="pygmalion",
            is_public=True,
            tags=["test", "demo", "v2"],
            category="tutorial",
        )
        print(f"✅ Created character: {test_char.name}")
        print(f"   ID: {test_char.id}")
        print(f"   Owner: {test_char.user_id}")
        print(f"   Public: {test_char.is_public}")
        print(f"   Tags: {test_char.tags}")
        print(f"   Category: {test_char.category}")

        # Test get_user_characters
        user_chars = await char_repo.get_user_characters(test_user.id)
        assert len(user_chars) >= 1, "No characters found for user"
        print(f"✅ Retrieved user characters: {len(user_chars)} found")

        # Test get_public_characters
        public_chars = await char_repo.get_public_characters(
            tags=["test"],
            limit=10
        )
        assert len(public_chars) >= 1, "No public characters found"
        print(f"✅ Retrieved public characters with tag filter: {len(public_chars)} found")

        # Test voice permission
        can_use_voice = await char_repo.can_use_voice_model(
            test_char.id,
            test_user.id
        )
        assert can_use_voice is True, "Owner should have voice access"
        print(f"✅ Voice permission check passed (owner has access)")

        print("\n3️⃣ Testing Base CRUD Operations")
        print("-" * 60)

        # Test exists
        exists = await user_repo.exists(test_user.id)
        assert exists is True, "Exists check failed"
        print(f"✅ Exists check passed")

        # Test get
        retrieved = await user_repo.get(test_user.id)
        assert retrieved.id == test_user.id, "Get by ID failed"
        print(f"✅ Get by ID passed")

        # Test get_multi with filters
        users = await user_repo.get_multi(role="user", limit=10)
        assert len(users) >= 1, "Get multi with filters failed"
        print(f"✅ Get multi with filters: {len(users)} users found")

        # Cleanup
        await user_repo.delete(test_user.id)
        print(f"\n🧹 Cleaned up test data")

        await session.commit()

    print("\n✅ All repository tests passed!\n")


async def main():
    """Run all tests."""
    print("\n")
    print("=" * 60)
    print("  COGNITIA V2 - PHASE 2 TESTING")
    print("  Repositories & Services")
    print("=" * 60)

    try:
        await test_security()
        await test_repositories()

        print("\n" + "=" * 60)
        print("🎉 ALL PHASE 2 TESTS PASSED!")
        print("=" * 60)
        print("\n✅ Repository layer: WORKING")
        print("✅ Security utilities: WORKING")
        print("✅ Database operations: WORKING")
        print("\n")
        return 0

    except Exception as e:
        print(f"\n❌ TESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
