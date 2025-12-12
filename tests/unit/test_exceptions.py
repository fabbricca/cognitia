"""Unit tests for exception hierarchy."""

import pytest
from cognitia.core.exceptions import (
    CognitiaException,
    LLMConnectionError,
    LLMTimeoutError,
    ComponentInitializationError,
    MemoryPersistenceError,
)


def test_cognitia_exception_base():
    """Test base exception with context."""
    exc = CognitiaException("test error", context={"key": "value"})
    assert exc.message == "test error"
    assert exc.context == {"key": "value"}
    assert "key=value" in str(exc)


def test_llm_connection_error():
    """Test LLM connection error creation."""
    original = ConnectionError("Network unreachable")
    exc = LLMConnectionError("http://localhost:11434", original)

    assert exc.url == "http://localhost:11434"
    assert exc.original_error is original
    assert "localhost:11434" in str(exc)


def test_llm_timeout_error():
    """Test LLM timeout error."""
    exc = LLMTimeoutError(30.0, "http://localhost:11434")

    assert exc.timeout_seconds == 30.0
    assert exc.url == "http://localhost:11434"
    assert "30" in str(exc)


def test_component_initialization_error():
    """Test component initialization error."""
    exc = ComponentInitializationError("LLMProcessor", "API key missing")

    assert exc.component_name == "LLMProcessor"
    assert "LLMProcessor" in str(exc)
    assert "API key missing" in str(exc)


def test_memory_persistence_error():
    """Test memory persistence error."""
    exc = MemoryPersistenceError("save", "/path/to/memory.json", "Permission denied")

    assert exc.operation == "save"
    assert exc.path == "/path/to/memory.json"
    assert "save" in str(exc)
    assert "Permission denied" in str(exc)


def test_exception_inheritance():
    """Test exception hierarchy."""
    assert issubclass(LLMConnectionError, CognitiaException)
    assert issubclass(ComponentInitializationError, CognitiaException)
    assert issubclass(MemoryPersistenceError, CognitiaException)
