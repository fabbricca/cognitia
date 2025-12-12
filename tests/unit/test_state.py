"""Unit tests for thread-safe state management."""

import pytest
import threading
import time
from cognitia.core.state import ThreadSafeConversationState, ConversationMessage


def test_conversation_state_initialization():
    """Test basic initialization."""
    state = ThreadSafeConversationState()
    assert len(state) == 0
    assert state.get_version() == 0


def test_conversation_state_with_initial_messages():
    """Test initialization with messages."""
    initial = [
        {"role": "system", "content": "You are an assistant"},
        {"role": "user", "content": "Hello"}
    ]
    state = ThreadSafeConversationState(initial)

    assert len(state) == 2
    messages = state.get_messages()
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_add_message():
    """Test adding messages."""
    state = ThreadSafeConversationState()

    version1 = state.add_message("user", "Hello")
    assert version1 == 1
    assert len(state) == 1

    version2 = state.add_message("assistant", "Hi there")
    assert version2 == 2
    assert len(state) == 2


def test_get_messages_returns_copy():
    """Test that get_messages returns a copy."""
    state = ThreadSafeConversationState()
    state.add_message("user", "Original")

    messages = state.get_messages()
    messages[0]["content"] = "Modified"

    # Original should be unchanged
    original = state.get_messages()
    assert original[0]["content"] == "Original"


def test_get_recent_messages():
    """Test retrieving recent messages."""
    state = ThreadSafeConversationState()

    for i in range(10):
        state.add_message("user", f"Message {i}")

    recent = state.get_recent_messages(3)
    assert len(recent) == 3
    assert recent[0]["content"] == "Message 7"
    assert recent[2]["content"] == "Message 9"


def test_clear_conversation():
    """Test clearing conversation."""
    state = ThreadSafeConversationState()
    state.add_message("system", "System prompt")
    state.add_message("user", "Hello")
    state.add_message("assistant", "Hi")

    # Clear but keep system prompts
    state.clear(keep_system_prompts=True)
    assert len(state) == 1
    assert state.get_messages()[0]["role"] == "system"

    # Clear everything
    state.add_message("user", "Test")
    state.clear(keep_system_prompts=False)
    assert len(state) == 0


def test_thread_safety_concurrent_adds():
    """Test thread safety with concurrent modifications."""
    state = ThreadSafeConversationState()
    num_threads = 10
    messages_per_thread = 100

    def add_messages(thread_id):
        for i in range(messages_per_thread):
            state.add_message("user", f"Thread {thread_id} message {i}")

    threads = [
        threading.Thread(target=add_messages, args=(i,))
        for i in range(num_threads)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify all messages added
    assert len(state) == num_threads * messages_per_thread

    # Verify version incremented correctly
    assert state.get_version() == num_threads * messages_per_thread


def test_thread_safety_concurrent_reads():
    """Test thread safety with concurrent reads."""
    state = ThreadSafeConversationState()

    # Add initial messages
    for i in range(100):
        state.add_message("user", f"Message {i}")

    results = []

    def read_messages():
        messages = state.get_messages()
        results.append(len(messages))

    # Start multiple reader threads
    threads = [threading.Thread(target=read_messages) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All readers should see same count
    assert all(count == 100 for count in results)


def test_conversation_message_immutability():
    """Test that ConversationMessage is immutable."""
    msg = ConversationMessage(role="user", content="Test")

    with pytest.raises(AttributeError):
        msg.role = "assistant"  # Should fail - frozen dataclass

    with pytest.raises(AttributeError):
        msg.content = "Modified"  # Should fail


def test_version_tracking():
    """Test version tracking for change detection."""
    state = ThreadSafeConversationState()

    version1 = state.get_version()
    state.add_message("user", "Test")
    version2 = state.get_version()

    assert version2 > version1

    state.clear()
    version3 = state.get_version()

    assert version3 > version2
