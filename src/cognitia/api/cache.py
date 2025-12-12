"""Redis caching layer for session and data caching.

Provides fast access to:
- User sessions
- Recent chat history
- Character preprompts
- Active WebSocket connections
"""

import json
import os
from datetime import timedelta
from typing import Any, Optional

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from loguru import logger

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SESSION = int(os.getenv("CACHE_TTL_SESSION", "3600"))  # 1 hour
CACHE_TTL_CHAT = int(os.getenv("CACHE_TTL_CHAT", "300"))  # 5 minutes
CACHE_TTL_CHARACTER = int(os.getenv("CACHE_TTL_CHARACTER", "3600"))  # 1 hour

# Key prefixes
PREFIX_SESSION = "session:"
PREFIX_USER = "user:"
PREFIX_CHAT = "chat:"
PREFIX_MESSAGES = "messages:"
PREFIX_CHARACTER = "character:"
PREFIX_ACTIVE_WS = "ws:"


class CacheManager:
    """Redis-based cache manager with fallback to in-memory cache."""
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self._memory_cache: dict[str, tuple[Any, float]] = {}
        self._connected = False
    
    async def connect(self):
        """Connect to Redis server."""
        if not REDIS_AVAILABLE:
            logger.warning("Redis not available, using in-memory cache")
            return
        
        try:
            self.redis = redis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            self._connected = True
            logger.info(f"Connected to Redis at {REDIS_URL}")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}, using in-memory cache")
            self.redis = None
            self._connected = False
    
    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
    
    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set a cache value with TTL."""
        try:
            serialized = json.dumps(value) if not isinstance(value, str) else value
            
            if self._connected and self.redis:
                await self.redis.setex(key, ttl, serialized)
            else:
                import time
                self._memory_cache[key] = (serialized, time.time() + ttl)
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def get(self, key: str) -> Optional[Any]:
        """Get a cache value."""
        try:
            if self._connected and self.redis:
                value = await self.redis.get(key)
            else:
                import time
                cached = self._memory_cache.get(key)
                if cached and cached[1] > time.time():
                    value = cached[0]
                else:
                    if cached:
                        del self._memory_cache[key]
                    value = None
            
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    async def delete(self, key: str) -> bool:
        """Delete a cache value."""
        try:
            if self._connected and self.redis:
                await self.redis.delete(key)
            else:
                self._memory_cache.pop(key, None)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        try:
            if self._connected and self.redis:
                keys = await self.redis.keys(pattern)
                if keys:
                    return await self.redis.delete(*keys)
            else:
                import fnmatch
                deleted = 0
                to_delete = [k for k in self._memory_cache if fnmatch.fnmatch(k, pattern)]
                for k in to_delete:
                    del self._memory_cache[k]
                    deleted += 1
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Cache delete pattern error: {e}")
            return 0
    
    # Session management
    async def set_session(self, user_id: str, session_data: dict, ttl: int = CACHE_TTL_SESSION):
        """Cache user session data."""
        return await self.set(f"{PREFIX_SESSION}{user_id}", session_data, ttl)
    
    async def get_session(self, user_id: str) -> Optional[dict]:
        """Get cached user session."""
        return await self.get(f"{PREFIX_SESSION}{user_id}")
    
    async def delete_session(self, user_id: str):
        """Delete user session from cache."""
        return await self.delete(f"{PREFIX_SESSION}{user_id}")
    
    # User data caching
    async def set_user(self, user_id: str, user_data: dict, ttl: int = CACHE_TTL_SESSION):
        """Cache user data."""
        return await self.set(f"{PREFIX_USER}{user_id}", user_data, ttl)
    
    async def get_user(self, user_id: str) -> Optional[dict]:
        """Get cached user data."""
        return await self.get(f"{PREFIX_USER}{user_id}")
    
    async def invalidate_user(self, user_id: str):
        """Invalidate all user-related cache."""
        await self.delete(f"{PREFIX_USER}{user_id}")
        await self.delete(f"{PREFIX_SESSION}{user_id}")
        await self.delete_pattern(f"{PREFIX_CHAT}*:{user_id}")
    
    # Chat caching
    async def set_chat(self, chat_id: str, chat_data: dict, ttl: int = CACHE_TTL_CHAT):
        """Cache chat data."""
        return await self.set(f"{PREFIX_CHAT}{chat_id}", chat_data, ttl)
    
    async def get_chat(self, chat_id: str) -> Optional[dict]:
        """Get cached chat data."""
        return await self.get(f"{PREFIX_CHAT}{chat_id}")
    
    async def invalidate_chat(self, chat_id: str):
        """Invalidate chat cache."""
        await self.delete(f"{PREFIX_CHAT}{chat_id}")
        await self.delete(f"{PREFIX_MESSAGES}{chat_id}")
    
    # Messages caching (recent messages for fast loading)
    async def set_recent_messages(self, chat_id: str, messages: list, ttl: int = CACHE_TTL_CHAT):
        """Cache recent messages for a chat."""
        return await self.set(f"{PREFIX_MESSAGES}{chat_id}", messages, ttl)
    
    async def get_recent_messages(self, chat_id: str) -> Optional[list]:
        """Get cached recent messages."""
        return await self.get(f"{PREFIX_MESSAGES}{chat_id}")
    
    async def append_message(self, chat_id: str, message: dict):
        """Append a message to the cached messages list."""
        messages = await self.get_recent_messages(chat_id) or []
        messages.append(message)
        # Keep only last 50 messages in cache
        if len(messages) > 50:
            messages = messages[-50:]
        await self.set_recent_messages(chat_id, messages)
    
    # Character preprompt caching
    async def set_character(self, character_id: str, character_data: dict, ttl: int = CACHE_TTL_CHARACTER):
        """Cache character data including preprompt."""
        return await self.set(f"{PREFIX_CHARACTER}{character_id}", character_data, ttl)
    
    async def get_character(self, character_id: str) -> Optional[dict]:
        """Get cached character data."""
        return await self.get(f"{PREFIX_CHARACTER}{character_id}")
    
    async def invalidate_character(self, character_id: str):
        """Invalidate character cache."""
        await self.delete(f"{PREFIX_CHARACTER}{character_id}")
    
    # Active WebSocket tracking
    async def register_ws(self, user_id: str, connection_id: str):
        """Register an active WebSocket connection."""
        key = f"{PREFIX_ACTIVE_WS}{user_id}"
        if self._connected and self.redis:
            await self.redis.sadd(key, connection_id)
            await self.redis.expire(key, CACHE_TTL_SESSION)
        else:
            connections = self._memory_cache.get(key, (set(), 0))[0]
            if not isinstance(connections, set):
                connections = set()
            connections.add(connection_id)
            import time
            self._memory_cache[key] = (connections, time.time() + CACHE_TTL_SESSION)
    
    async def unregister_ws(self, user_id: str, connection_id: str):
        """Unregister a WebSocket connection."""
        key = f"{PREFIX_ACTIVE_WS}{user_id}"
        if self._connected and self.redis:
            await self.redis.srem(key, connection_id)
        else:
            cached = self._memory_cache.get(key)
            if cached and isinstance(cached[0], set):
                cached[0].discard(connection_id)
    
    async def get_active_connections(self, user_id: str) -> set:
        """Get active WebSocket connections for a user."""
        key = f"{PREFIX_ACTIVE_WS}{user_id}"
        if self._connected and self.redis:
            return await self.redis.smembers(key)
        else:
            cached = self._memory_cache.get(key)
            if cached and isinstance(cached[0], set):
                return cached[0]
            return set()


# Singleton instance
cache = CacheManager()


async def init_cache():
    """Initialize cache connection."""
    await cache.connect()


async def close_cache():
    """Close cache connection."""
    await cache.close()
