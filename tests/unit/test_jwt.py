"""
Unit tests for JWT handling.

Tests token creation, verification, and expiration.
"""

import pytest
import time
from datetime import datetime, timedelta, timezone

try:
    from cognitia.auth.jwt_handler import JWTHandler, TokenPayload
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False


@pytest.fixture
def jwt_handler():
    """Create JWT handler with test secret."""
    if not JWT_AVAILABLE:
        pytest.skip("pyjwt not installed")
    return JWTHandler(secret_key="test_secret_key_12345")


def test_create_access_token(jwt_handler):
    """Test access token creation."""
    token = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=["user"],
        permissions=["chat:send", "memory:read"]
    )

    assert isinstance(token, str)
    assert len(token) > 0


def test_verify_valid_token(jwt_handler):
    """Test verification of valid token."""
    token = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=["user", "developer"],
        permissions=["chat:send", "memory:read", "tool:web_search"]
    )

    payload = jwt_handler.verify_token(token)

    assert payload is not None
    assert payload.user_id == "user123"
    assert payload.username == "testuser"
    assert payload.email == "test@example.com"
    assert "user" in payload.roles
    assert "developer" in payload.roles
    assert "chat:send" in payload.permissions
    assert "memory:read" in payload.permissions
    assert "tool:web_search" in payload.permissions
    assert payload.token_type == "access"
    assert isinstance(payload.exp, datetime)
    assert isinstance(payload.iat, datetime)
    assert len(payload.jti) > 0


def test_verify_invalid_token(jwt_handler):
    """Test verification of invalid token."""
    payload = jwt_handler.verify_token("invalid.token.here")
    assert payload is None


def test_verify_token_wrong_secret():
    """Test that token verification fails with wrong secret."""
    if not JWT_AVAILABLE:
        pytest.skip("pyjwt not installed")

    handler1 = JWTHandler(secret_key="secret1")
    handler2 = JWTHandler(secret_key="secret2")

    token = handler1.create_access_token(
        user_id="user123",
        username="test",
        email="test@example.com",
        roles=[],
        permissions=[]
    )

    # Should fail with different secret
    payload = handler2.verify_token(token)
    assert payload is None


def test_create_refresh_token(jwt_handler):
    """Test refresh token creation."""
    token = jwt_handler.create_refresh_token(
        user_id="user123",
        username="testuser"
    )

    assert isinstance(token, str)
    assert len(token) > 0

    # Decode without verification to check type
    payload = jwt_handler.decode_without_verification(token)
    assert payload is not None
    assert payload["type"] == "refresh"
    assert payload["sub"] == "user123"


def test_refresh_token_not_accepted_as_access(jwt_handler):
    """Test that refresh tokens are rejected for access."""
    refresh_token = jwt_handler.create_refresh_token(
        user_id="user123",
        username="testuser"
    )

    # Should fail because type is "refresh" not "access"
    payload = jwt_handler.verify_token(refresh_token)
    assert payload is None


def test_decode_without_verification(jwt_handler):
    """Test decoding without signature verification."""
    token = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=["user"],
        permissions=["chat:send"]
    )

    payload = jwt_handler.decode_without_verification(token)

    assert payload is not None
    assert payload["user_id"] == "user123"
    assert payload["username"] == "testuser"
    assert payload["type"] == "access"


def test_extract_jti(jwt_handler):
    """Test extracting JWT ID from token."""
    token = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=[],
        permissions=[]
    )

    jti = jwt_handler.extract_jti(token)

    assert jti is not None
    assert isinstance(jti, str)
    assert len(jti) > 0


def test_token_expiration_field(jwt_handler):
    """Test that token has expiration time set."""
    token = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=[],
        permissions=[]
    )

    payload = jwt_handler.verify_token(token)

    assert payload is not None
    assert payload.exp > datetime.now(timezone.utc)

    # Should expire in approximately 1 hour
    expected_exp = datetime.now(timezone.utc) + timedelta(minutes=60)
    time_diff = abs((payload.exp - expected_exp).total_seconds())
    assert time_diff < 60  # Within 1 minute tolerance


def test_token_issued_at(jwt_handler):
    """Test that token has issued-at time set."""
    before = datetime.now(timezone.utc)

    token = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=[],
        permissions=[]
    )

    after = datetime.now(timezone.utc)
    payload = jwt_handler.verify_token(token)

    assert payload is not None
    assert before <= payload.iat <= after


def test_different_tokens_have_different_jti(jwt_handler):
    """Test that each token gets a unique JWT ID."""
    token1 = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=[],
        permissions=[]
    )

    token2 = jwt_handler.create_access_token(
        user_id="user123",
        username="testuser",
        email="test@example.com",
        roles=[],
        permissions=[]
    )

    jti1 = jwt_handler.extract_jti(token1)
    jti2 = jwt_handler.extract_jti(token2)

    assert jti1 != jti2
