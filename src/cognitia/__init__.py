"""Cognitia - Voice Assistant using ONNX models for speech synthesis and recognition."""

__version__ = "0.1.0"

# Conditionally import core engine (requires GPU dependencies)
try:
    from .core.engine import Cognitia, CognitiaConfig
    __all__ = ["Cognitia", "CognitiaConfig"]
except ImportError:
    # Core module not available (e.g., in Entrance-only container)
    __all__ = []
