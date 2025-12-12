"""Pytest configuration and shared fixtures."""

import pytest
import queue
import threading
from unittest.mock import Mock, MagicMock
import numpy as np
from pathlib import Path


# ============================================================================
# Mock Components
# ============================================================================

@pytest.fixture
def mock_asr():
    """Mock ASR model."""
    asr = Mock()
    asr.transcribe = Mock(return_value="test transcription")
    asr.transcribe_file = Mock(return_value="")
    return asr


@pytest.fixture
def mock_tts():
    """Mock TTS model."""
    tts = Mock()
    tts.sample_rate = 24000
    tts.generate_speech_audio = Mock(
        return_value=np.array([0.1, 0.2, 0.3], dtype=np.float32)
    )
    return tts


@pytest.fixture
def mock_audio_io():
    """Mock audio I/O system."""
    audio = Mock()
    audio.get_sample_queue = Mock(return_value=queue.Queue())
    audio.start_listening = Mock()
    audio.stop_listening = Mock()
    audio.start_speaking = Mock()
    audio.check_if_speaking = Mock(return_value=False)
    audio.measure_percentage_spoken = Mock(return_value=(False, 100))
    audio.stop_speaking = Mock()
    return audio


# ============================================================================
# Queues and Events
# ============================================================================

@pytest.fixture
def mock_queues():
    """Create standard message queues."""
    return {
        "llm_input": queue.Queue(),
        "tts_input": queue.Queue(),
        "audio_output": queue.Queue(),
    }


@pytest.fixture
def mock_events():
    """Create standard synchronization events."""
    return {
        "shutdown": threading.Event(),
        "processing": threading.Event(),
        "speaking": threading.Event(),
    }


# ============================================================================
# Temporary Files
# ============================================================================

@pytest.fixture
def temp_memory_file(tmp_path):
    """Create temporary memory persistence file."""
    return tmp_path / "test_memory.json"


# ============================================================================
# Test Utilities
# ============================================================================

class QueueReader:
    """Helper for reading from queues in tests."""

    def __init__(self, q: queue.Queue, timeout: float = 1.0):
        self.queue = q
        self.timeout = timeout

    def get_all(self) -> list:
        """Get all items currently in queue."""
        items = []
        while True:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return items

    def wait_for(self, count: int) -> list:
        """Wait for N items."""
        items = []
        for _ in range(count):
            items.append(self.queue.get(timeout=self.timeout))
        return items


@pytest.fixture
def queue_reader():
    """Factory for QueueReader instances."""
    def _factory(q: queue.Queue) -> QueueReader:
        return QueueReader(q)
    return _factory
