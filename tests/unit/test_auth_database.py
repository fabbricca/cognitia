"""
Unit tests for user database.

Tests user CRUD operations, password hashing, and permissions.
"""

import pytest
from pathlib import Path
from datetime import datetime

# Import will fail if bcrypt not installed - that's expected
try:
    from cognitia.auth.database import UserDatabase
    from cognitia.auth.models import User
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False


@pytest.fixture
def temp_db(tmp_path):
    """Create temporary database for testing."""
    if not BCRYPT_AVAILABLE:
        pytest.skip("bcrypt not installed")
    return UserDatabase(tmp_path / "test_users.db")


def test_create_user(temp_db):
    """Test user creation with password hashing."""
    user = temp_db.create_user(
        username="testuser",
        email="test@example.com",
        password="password123"
    )

    assert user.username == "testuser"
    assert user.email == "test@example.com"
    assert user.password_hash != "password123"  # Should be hashed
    assert user.is_active is True
    assert user.is_admin is False
    assert isinstance(user.created_at, datetime)


def test_create_admin_user(temp_db):
    """Test admin user creation."""
    user = temp_db.create_user(
        username="admin",
        email="admin@example.com",
        password="adminpass",
        is_admin=True
    )

    assert user.is_admin is True


def test_duplicate_username(temp_db):
    """Test that duplicate usernames are rejected."""
    temp_db.create_user("testuser", "test1@example.com", "pass1")

    with pytest.raises(Exception):  # sqlite3.IntegrityError
        temp_db.create_user("testuser", "test2@example.com", "pass2")


def test_duplicate_email(temp_db):
    """Test that duplicate emails are rejected."""
    temp_db.create_user("user1", "test@example.com", "pass1")

    with pytest.raises(Exception):  # sqlite3.IntegrityError
        temp_db.create_user("user2", "test@example.com", "pass2")


def test_verify_password(temp_db):
    """Test password verification."""
    user = temp_db.create_user("testuser", "test@example.com", "password123")

    # Correct password
    assert temp_db.verify_password(user, "password123")

    # Wrong password
    assert not temp_db.verify_password(user, "wrongpassword")


def test_get_user_by_username(temp_db):
    """Test user retrieval by username."""
    temp_db.create_user("testuser", "test@example.com", "password123")

    user = temp_db.get_user_by_username("testuser")
    assert user is not None
    assert user.username == "testuser"
    assert user.email == "test@example.com"

    nonexistent = temp_db.get_user_by_username("nobody")
    assert nonexistent is None


def test_get_user_by_id(temp_db):
    """Test user retrieval by ID."""
    created = temp_db.create_user("testuser", "test@example.com", "password123")

    user = temp_db.get_user_by_id(created.user_id)
    assert user is not None
    assert user.user_id == created.user_id
    assert user.username == "testuser"

    nonexistent = temp_db.get_user_by_id("fake-uuid")
    assert nonexistent is None


def test_list_users(temp_db):
    """Test listing all users."""
    temp_db.create_user("user1", "user1@example.com", "pass1")
    temp_db.create_user("user2", "user2@example.com", "pass2")
    temp_db.create_user("user3", "user3@example.com", "pass3")

    users = temp_db.list_users()
    assert len(users) == 3
    assert {u.username for u in users} == {"user1", "user2", "user3"}


def test_update_user(temp_db):
    """Test updating user information."""
    user = temp_db.create_user("testuser", "test@example.com", "password123")

    # Update email and admin status
    user.email = "newemail@example.com"
    user.is_admin = True

    success = temp_db.update_user(user)
    assert success

    # Verify update
    updated = temp_db.get_user_by_id(user.user_id)
    assert updated.email == "newemail@example.com"
    assert updated.is_admin is True


def test_delete_user(temp_db):
    """Test user deletion."""
    user = temp_db.create_user("testuser", "test@example.com", "password123")

    success = temp_db.delete_user(user.user_id)
    assert success

    # Verify deletion
    deleted = temp_db.get_user_by_id(user.user_id)
    assert deleted is None


def test_get_user_permissions(temp_db):
    """Test getting user permissions (returns empty list without roles)."""
    user = temp_db.create_user("testuser", "test@example.com", "password123")

    permissions = temp_db.get_user_permissions(user.user_id)
    assert isinstance(permissions, list)
    assert len(permissions) == 0  # No roles assigned


def test_get_user_roles(temp_db):
    """Test getting user roles (returns empty list initially)."""
    user = temp_db.create_user("testuser", "test@example.com", "password123")

    roles = temp_db.get_user_roles(user.user_id)
    assert isinstance(roles, list)
    assert len(roles) == 0  # No roles assigned


def test_database_persistence(tmp_path):
    """Test that database persists across connections."""
    if not BCRYPT_AVAILABLE:
        pytest.skip("bcrypt not installed")

    db_path = tmp_path / "test_users.db"

    # Create user in first connection
    db1 = UserDatabase(db_path)
    user = db1.create_user("testuser", "test@example.com", "password123")
    user_id = user.user_id

    # Close and reopen database
    del db1
    db2 = UserDatabase(db_path)

    # Verify user still exists
    user = db2.get_user_by_id(user_id)
    assert user is not None
    assert user.username == "testuser"
