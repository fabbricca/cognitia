"""
Comprehensive API endpoint tests for Cognitia.
Run with: pytest tests/test_api_endpoints.py -v
"""

import pytest
from httpx import AsyncClient, ASGITransport
from uuid import UUID
import asyncio

# Import the FastAPI app
from cognitia.api.main import app
from cognitia.api.database import init_db, engine
from sqlalchemy import text


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """Initialize the database before tests."""
    await init_db()
    yield
    # Cleanup: drop all data after tests
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM messages"))
        await conn.execute(text("DELETE FROM chats"))
        await conn.execute(text("DELETE FROM characters"))
        await conn.execute(text("DELETE FROM users"))


@pytest.fixture
async def client():
    """Create an async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client(client):
    """Create an authenticated client with a test user."""
    import time
    email = f"test_{time.time_ns()}@test.com"
    password = "testpassword123"
    
    # Register
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password}
    )
    assert response.status_code == 201
    
    # Login
    response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    data = response.json()
    token = data["access_token"]
    
    # Return client with auth header helper
    class AuthClient:
        def __init__(self, client, token):
            self.client = client
            self.token = token
            self.headers = {"Authorization": f"Bearer {token}"}
        
        async def get(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self.headers)
            return await self.client.get(url, **kwargs)
        
        async def post(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self.headers)
            return await self.client.post(url, **kwargs)
        
        async def put(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self.headers)
            return await self.client.put(url, **kwargs)
        
        async def delete(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self.headers)
            return await self.client.delete(url, **kwargs)
    
    return AuthClient(client, token)


class TestHealth:
    """Health check endpoint tests."""
    
    async def test_health_check(self, client):
        """Test that health endpoint returns OK."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestAuth:
    """Authentication endpoint tests."""
    
    async def test_register_user(self, client):
        """Test user registration."""
        import time
        email = f"register_test_{time.time_ns()}@test.com"
        response = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "testpassword123"}
        )
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
    
    async def test_register_duplicate_email(self, client):
        """Test that duplicate email registration fails."""
        import time
        email = f"dup_test_{time.time_ns()}@test.com"
        
        # First registration
        response = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "testpassword123"}
        )
        assert response.status_code == 201
        
        # Second registration with same email
        response = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "testpassword123"}
        )
        assert response.status_code == 400
    
    async def test_register_invalid_email(self, client):
        """Test that invalid email fails validation."""
        response = await client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "password": "testpassword123"}
        )
        assert response.status_code == 422
    
    async def test_register_short_password(self, client):
        """Test that short password fails validation."""
        response = await client.post(
            "/api/auth/register",
            json={"email": "short@test.com", "password": "short"}
        )
        assert response.status_code == 422
    
    async def test_login_user(self, client):
        """Test user login."""
        import time
        email = f"login_test_{time.time_ns()}@test.com"
        password = "testpassword123"
        
        # Register first
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": password}
        )
        
        # Login
        response = await client.post(
            "/api/auth/login",
            json={"email": email, "password": password}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
    
    async def test_login_wrong_password(self, client):
        """Test that wrong password fails."""
        import time
        email = f"wrongpw_test_{time.time_ns()}@test.com"
        
        # Register
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "testpassword123"}
        )
        
        # Login with wrong password
        response = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrongpassword"}
        )
        assert response.status_code == 401
    
    async def test_get_current_user(self, auth_client):
        """Test getting current user info."""
        response = await auth_client.get("/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "email" in data
        assert "created_at" in data
    
    async def test_unauthorized_access(self, client):
        """Test that unauthorized requests are rejected."""
        response = await client.get("/api/auth/me")
        assert response.status_code == 401


class TestCharacters:
    """Character endpoint tests."""
    
    async def test_list_characters_empty(self, auth_client):
        """Test listing characters when none exist."""
        response = await auth_client.get("/api/characters/")
        assert response.status_code == 200
        data = response.json()
        assert "characters" in data
        assert isinstance(data["characters"], list)
    
    async def test_create_character(self, auth_client):
        """Test creating a character."""
        response = await auth_client.post(
            "/api/characters/",
            json={
                "name": "Test Bot",
                "system_prompt": "You are a helpful test assistant",
                "voice_model": "glados"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Bot"
        assert data["system_prompt"] == "You are a helpful test assistant"
        assert data["voice_model"] == "glados"
        assert "id" in data
        UUID(data["id"])  # Validate UUID format
    
    async def test_create_character_minimal(self, auth_client):
        """Test creating a character with minimal fields."""
        response = await auth_client.post(
            "/api/characters/",
            json={
                "name": "Minimal Bot",
                "system_prompt": "You are minimal"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Bot"
        assert data["voice_model"] == "af_bella"  # Default value
    
    async def test_create_character_missing_name(self, auth_client):
        """Test that missing name fails validation."""
        response = await auth_client.post(
            "/api/characters/",
            json={"system_prompt": "You are missing a name"}
        )
        assert response.status_code == 422
    
    async def test_create_character_missing_prompt(self, auth_client):
        """Test that missing system_prompt fails validation."""
        response = await auth_client.post(
            "/api/characters/",
            json={"name": "No Prompt Bot"}
        )
        assert response.status_code == 422
    
    async def test_get_character(self, auth_client):
        """Test getting a character by ID."""
        # Create first
        create_response = await auth_client.post(
            "/api/characters/",
            json={
                "name": "Get Test Bot",
                "system_prompt": "You are a get test"
            }
        )
        char_id = create_response.json()["id"]
        
        # Get
        response = await auth_client.get(f"/api/characters/{char_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == char_id
        assert data["name"] == "Get Test Bot"
    
    async def test_get_character_not_found(self, auth_client):
        """Test getting a non-existent character."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await auth_client.get(f"/api/characters/{fake_id}")
        assert response.status_code == 404
    
    async def test_update_character(self, auth_client):
        """Test updating a character."""
        # Create first
        create_response = await auth_client.post(
            "/api/characters/",
            json={
                "name": "Update Test Bot",
                "system_prompt": "Original prompt"
            }
        )
        char_id = create_response.json()["id"]
        
        # Update
        response = await auth_client.put(
            f"/api/characters/{char_id}",
            json={
                "name": "Updated Bot",
                "system_prompt": "Updated prompt"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Bot"
        assert data["system_prompt"] == "Updated prompt"
    
    async def test_delete_character(self, auth_client):
        """Test deleting a character."""
        # Create first
        create_response = await auth_client.post(
            "/api/characters/",
            json={
                "name": "Delete Test Bot",
                "system_prompt": "To be deleted"
            }
        )
        char_id = create_response.json()["id"]
        
        # Delete
        response = await auth_client.delete(f"/api/characters/{char_id}")
        assert response.status_code == 204
        
        # Verify deleted
        get_response = await auth_client.get(f"/api/characters/{char_id}")
        assert get_response.status_code == 404


class TestChats:
    """Chat endpoint tests."""
    
    @pytest.fixture
    async def character(self, auth_client):
        """Create a character for chat tests."""
        response = await auth_client.post(
            "/api/characters/",
            json={
                "name": "Chat Test Bot",
                "system_prompt": "You are for chat testing"
            }
        )
        return response.json()
    
    async def test_list_chats_empty(self, auth_client):
        """Test listing chats when none exist."""
        response = await auth_client.get("/api/chats/")
        assert response.status_code == 200
        data = response.json()
        assert "chats" in data
        assert isinstance(data["chats"], list)
    
    async def test_create_chat(self, auth_client, character):
        """Test creating a chat."""
        response = await auth_client.post(
            "/api/chats/",
            json={
                "character_id": character["id"],
                "title": "Test Chat"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["character_id"] == character["id"]
        assert data["title"] == "Test Chat"
        assert "id" in data
    
    async def test_create_chat_no_title(self, auth_client, character):
        """Test creating a chat without title."""
        response = await auth_client.post(
            "/api/chats/",
            json={"character_id": character["id"]}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] is None
    
    async def test_create_chat_invalid_character(self, auth_client):
        """Test creating a chat with invalid character ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await auth_client.post(
            "/api/chats/",
            json={"character_id": fake_id}
        )
        assert response.status_code == 404
    
    async def test_get_chat(self, auth_client, character):
        """Test getting a chat by ID."""
        # Create first
        create_response = await auth_client.post(
            "/api/chats/",
            json={
                "character_id": character["id"],
                "title": "Get Test Chat"
            }
        )
        chat_id = create_response.json()["id"]
        
        # Get
        response = await auth_client.get(f"/api/chats/{chat_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == chat_id
        assert data["title"] == "Get Test Chat"
    
    async def test_delete_chat(self, auth_client, character):
        """Test deleting a chat."""
        # Create first
        create_response = await auth_client.post(
            "/api/chats/",
            json={
                "character_id": character["id"],
                "title": "Delete Test Chat"
            }
        )
        chat_id = create_response.json()["id"]
        
        # Delete
        response = await auth_client.delete(f"/api/chats/{chat_id}")
        assert response.status_code == 204
        
        # Verify deleted
        get_response = await auth_client.get(f"/api/chats/{chat_id}")
        assert get_response.status_code == 404


class TestMessages:
    """Message endpoint tests."""
    
    @pytest.fixture
    async def chat(self, auth_client):
        """Create a character and chat for message tests."""
        # Create character
        char_response = await auth_client.post(
            "/api/characters/",
            json={
                "name": "Message Test Bot",
                "system_prompt": "You are for message testing"
            }
        )
        character = char_response.json()
        
        # Create chat
        chat_response = await auth_client.post(
            "/api/chats/",
            json={
                "character_id": character["id"],
                "title": "Message Test Chat"
            }
        )
        return chat_response.json()
    
    async def test_list_messages_empty(self, auth_client, chat):
        """Test listing messages when none exist."""
        response = await auth_client.get(f"/api/chats/{chat['id']}/messages")
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) == 0
    
    async def test_add_user_message(self, auth_client, chat):
        """Test adding a user message."""
        response = await auth_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={
                "role": "user",
                "content": "Hello, bot!"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "user"
        assert data["content"] == "Hello, bot!"
        assert data["chat_id"] == chat["id"]
    
    async def test_add_assistant_message(self, auth_client, chat):
        """Test adding an assistant message."""
        response = await auth_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={
                "role": "assistant",
                "content": "Hello, human!"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "assistant"
        assert data["content"] == "Hello, human!"
    
    async def test_add_message_invalid_role(self, auth_client, chat):
        """Test that invalid role fails validation."""
        response = await auth_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={
                "role": "invalid",
                "content": "Invalid role"
            }
        )
        assert response.status_code == 422
    
    async def test_add_message_empty_content(self, auth_client, chat):
        """Test that empty content fails validation."""
        response = await auth_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={
                "role": "user",
                "content": ""
            }
        )
        assert response.status_code == 422
    
    async def test_list_messages(self, auth_client, chat):
        """Test listing messages after adding some."""
        # Add messages
        await auth_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={"role": "user", "content": "First message"}
        )
        await auth_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={"role": "assistant", "content": "Second message"}
        )
        
        # List
        response = await auth_client.get(f"/api/chats/{chat['id']}/messages")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) >= 2


class TestFavicon:
    """Favicon endpoint test."""
    
    async def test_favicon(self, client):
        """Test that favicon returns 204 No Content."""
        response = await client.get("/favicon.ico")
        assert response.status_code == 204
