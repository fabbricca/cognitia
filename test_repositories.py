"""Test script for repository layer."""

import asyncio
from uuid import uuid4

from src.cognitia.entrance.database import async_session_maker, User, Character
from src.cognitia.entrance.repositories import (
    UserRepository,
    CharacterRepository,
    ChatRepository,
    MessageRepository,
    SubscriptionRepository,
)


async def test_repositories():
    """Test all repositories."""
    print("🧪 Testing Cognitia v2 Repositories\n")

    async with async_session_maker() as session:
        # Initialize repositories
        user_repo = UserRepository(User, session)
        char_repo = CharacterRepository(Character, session)

        print("1️⃣ Testing UserRepository...")
        try:
            # Create test user
            test_user = await user_repo.create(
                email=f"test_{uuid4().hex[:8]}@example.com",
                password_hash="hashed_password_123",
                first_name="Test",
                last_name="User",
                role="user",
                email_verified=False,
            )
            print(f"   ✅ Created user: {test_user.email} (ID: {test_user.id})")

            # Test get_by_email
            found_user = await user_repo.get_by_email(test_user.email)
            assert found_user.id == test_user.id
            print(f"   ✅ Retrieved user by email")

            # Test email_exists
            exists = await user_repo.email_exists(test_user.email)
            assert exists is True
            print(f"   ✅ Email exists check passed")

            # Test update
            updated_user = await user_repo.update(
                test_user.id,
                email_verified=True,
                first_name="Updated"
            )
            assert updated_user.email_verified is True
            assert updated_user.first_name == "Updated"
            print(f"   ✅ Updated user successfully")

        except Exception as e:
            print(f"   ❌ UserRepository test failed: {e}")
            raise

        print("\n2️⃣ Testing CharacterRepository...")
        try:
            # Create test character
            test_char = await char_repo.create(
                user_id=test_user.id,
                name="Test Character",
                description="A test character",
                system_prompt="You are a test character.",
                voice_model="af_bella",
                prompt_template="pygmalion",
                is_public=True,
                tags=["test", "demo"],
                category="tutorial",
            )
            print(f"   ✅ Created character: {test_char.name} (ID: {test_char.id})")

            # Test get_user_characters
            user_chars = await char_repo.get_user_characters(test_user.id)
            assert len(user_chars) >= 1
            print(f"   ✅ Retrieved user characters: {len(user_chars)} found")

            # Test get_public_characters
            public_chars = await char_repo.get_public_characters(
                tags=["test"],
                limit=10
            )
            assert len(public_chars) >= 1
            print(f"   ✅ Retrieved public characters: {len(public_chars)} found")

            # Test voice permission
            can_use_voice = await char_repo.can_use_voice_model(
                test_char.id,
                test_user.id
            )
            assert can_use_voice is True  # Owner should always have access
            print(f"   ✅ Voice permission check passed")

        except Exception as e:
            print(f"   ❌ CharacterRepository test failed: {e}")
            raise

        print("\n3️⃣ Testing BaseRepository operations...")
        try:
            # Test exists
            exists = await user_repo.exists(test_user.id)
            assert exists is True
            print(f"   ✅ Exists check passed")

            # Test get
            retrieved = await user_repo.get(test_user.id)
            assert retrieved.id == test_user.id
            print(f"   ✅ Get by ID passed")

            # Test get_multi with filters
            users = await user_repo.get_multi(role="user", limit=10)
            assert len(users) >= 1
            print(f"   ✅ Get multi with filters: {len(users)} users")

        except Exception as e:
            print(f"   ❌ BaseRepository test failed: {e}")
            raise

        # Cleanup
        await user_repo.delete(test_user.id)
        print(f"\n🧹 Cleaned up test data")

        await session.commit()

    print("\n✅ All repository tests passed!")


async def test_security():
    """Test security utilities."""
    print("\n🔐 Testing Security Utilities\n")

    from src.cognitia.entrance.core.security import (
        hash_password,
        verify_password,
        create_jwt_token,
        decode_jwt_token,
    )

    # Test password hashing
    password = "test_password_123"
    hashed = hash_password(password)
    print(f"   ✅ Password hashed")

    # Test password verification
    is_valid = verify_password(password, hashed)
    assert is_valid is True
    print(f"   ✅ Password verification passed")

    is_invalid = verify_password("wrong_password", hashed)
    assert is_invalid is False
    print(f"   ✅ Invalid password correctly rejected")

    # Test JWT token creation
    user_id = uuid4()
    token = create_jwt_token(
        user_id=user_id,
        email="test@example.com",
        role="user",
        token_type="access",
        expires_minutes=60,
    )
    print(f"   ✅ JWT token created")

    # Test JWT token decoding
    payload = decode_jwt_token(token)
    assert payload.sub == str(user_id)
    assert payload.email == "test@example.com"
    assert payload.role == "user"
    assert payload.type == "access"
    print(f"   ✅ JWT token decoded and verified")

    print("\n✅ All security tests passed!")


async def main():
    """Run all tests."""
    try:
        await test_security()
        await test_repositories()
        print("\n🎉 All tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Tests failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
