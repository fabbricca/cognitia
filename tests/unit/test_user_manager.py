"""
Unit tests for user manager.

Tests login, token verification, and permission checking.
"""

import pytest
from pathlib import Path

try:
    from cognitia.auth.user_manager import UserManager
    from cognitia.auth.jwt_handler import TokenPayload
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False


@pytest.fixture
def user_manager(tmp_path):
    """Create user manager with temporary database."""
    if not AUTH_AVAILABLE:
        pytest.skip("auth dependencies not installed")

    db_path = tmp_path / "test_users.db"
    manager = UserManager(db_path, secret_key="test_secret_key")

    # Create test user
    manager.db.create_user(
        username="testuser",
        email="test@example.com",
        password="password123",
        is_admin=False
    )

    # Create admin user
    manager.db.create_user(
        username="admin",
        email="admin@example.com",
        password="adminpass",
        is_admin=True
    )

    return manager


def test_login_success(user_manager):
    """Test successful login."""
    result = user_manager.login("testuser", "password123")

    assert result is not None
    access_token, refresh_token = result

    assert isinstance(access_token, str)
    assert isinstance(refresh_token, str)
    assert len(access_token) > 0
    assert len(refresh_token) > 0


def test_login_wrong_password(user_manager):
    """Test login with wrong password."""
    result = user_manager.login("testuser", "wrongpassword")
    assert result is None


def test_login_nonexistent_user(user_manager):
    """Test login with nonexistent user."""
    result = user_manager.login("nobody", "password123")
    assert result is None


def test_login_inactive_user(user_manager):
    """Test login with inactive user."""
    # Create inactive user
    user = user_manager.db.create_user(
        username="inactive",
        email="inactive@example.com",
        password="password123"
    )

    # Deactivate user
    user.is_active = False
    user_manager.db.update_user(user)

    # Try to login
    result = user_manager.login("inactive", "password123")
    assert result is None


def test_admin_login_has_admin_permissions(user_manager):
    """Test that admin user gets admin permissions."""
    result = user_manager.login("admin", "adminpass")
    assert result is not None

    access_token, _ = result
    payload = user_manager.verify_token(access_token)

    assert payload is not None
    assert "admin" in payload.roles
    assert "admin:*" in payload.permissions


def test_verify_valid_token(user_manager):
    """Test token verification."""
    access_token, _ = user_manager.login("testuser", "password123")

    payload = user_manager.verify_token(access_token)

    assert payload is not None
    assert payload.username == "testuser"
    assert payload.email == "test@example.com"


def test_verify_invalid_token(user_manager):
    """Test verification of invalid token."""
    payload = user_manager.verify_token("invalid.token.here")
    assert payload is None


def test_has_permission_exact_match(user_manager):
    """Test permission checking with exact match."""
    # Create user with specific permission
    user = user_manager.db.create_user(
        username="permuser",
        email="perm@example.com",
        password="password123"
    )

    # Mock token payload with permissions
    payload = TokenPayload(
        user_id=user.user_id,
        username="permuser",
        email="perm@example.com",
        roles=["user"],
        permissions=["chat:send", "memory:read"],
        exp=None,  # type: ignore
        iat=None,  # type: ignore
        jti="test-jti",
        token_type="access"
    )

    assert user_manager.has_permission(payload, "chat:send")
    assert user_manager.has_permission(payload, "memory:read")
    assert not user_manager.has_permission(payload, "memory:write")


def test_has_permission_wildcard(user_manager):
    """Test permission checking with wildcard."""
    payload = TokenPayload(
        user_id="user123",
        username="test",
        email="test@example.com",
        roles=["user"],
        permissions=["chat:*", "memory:read"],
        exp=None,  # type: ignore
        iat=None,  # type: ignore
        jti="test-jti",
        token_type="access"
    )

    # Wildcard should match all chat permissions
    assert user_manager.has_permission(payload, "chat:send")
    assert user_manager.has_permission(payload, "chat:receive")
    assert user_manager.has_permission(payload, "chat:delete")

    # But not other resources
    assert user_manager.has_permission(payload, "memory:read")
    assert not user_manager.has_permission(payload, "memory:write")
    assert not user_manager.has_permission(payload, "tool:web_search")


def test_has_permission_admin_wildcard(user_manager):
    """Test that admin:* permission grants all permissions."""
    payload = TokenPayload(
        user_id="admin123",
        username="admin",
        email="admin@example.com",
        roles=["admin"],
        permissions=["admin:*"],
        exp=None,  # type: ignore
        iat=None,  # type: ignore
        jti="test-jti",
        token_type="access"
    )

    # Admin should have all permissions
    assert user_manager.has_permission(payload, "chat:send")
    assert user_manager.has_permission(payload, "memory:write")
    assert user_manager.has_permission(payload, "tool:web_search")
    assert user_manager.has_permission(payload, "admin:delete_user")
    assert user_manager.has_permission(payload, "anything:goes")


def test_refresh_access_token(user_manager):
    """Test refreshing access token."""
    # Login to get tokens
    access_token1, refresh_token = user_manager.login("testuser", "password123")

    # Refresh access token
    access_token2 = user_manager.refresh_access_token(refresh_token)

    assert access_token2 is not None
    assert isinstance(access_token2, str)
    assert access_token2 != access_token1  # Should be different

    # Verify new token works
    payload = user_manager.verify_token(access_token2)
    assert payload is not None
    assert payload.username == "testuser"


def test_refresh_with_invalid_token(user_manager):
    """Test refreshing with invalid token."""
    new_token = user_manager.refresh_access_token("invalid.token")
    assert new_token is None


def test_refresh_with_access_token_fails(user_manager):
    """Test that refresh fails when using access token."""
    access_token, _ = user_manager.login("testuser", "password123")

    # Try to refresh with access token (should fail)
    new_token = user_manager.refresh_access_token(access_token)
    assert new_token is None


def test_refresh_for_inactive_user(user_manager):
    """Test that refresh fails for inactive users."""
    # Login first
    _, refresh_token = user_manager.login("testuser", "password123")

    # Deactivate user
    user = user_manager.db.get_user_by_username("testuser")
    user.is_active = False
    user_manager.db.update_user(user)

    # Try to refresh (should fail)
    new_token = user_manager.refresh_access_token(refresh_token)
    assert new_token is None
