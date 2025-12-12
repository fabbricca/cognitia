"""
Domain-specific exception hierarchy for Cognitia.

All custom exceptions inherit from CognitiaException for consistent error handling.
"""

from typing import Any


class CognitiaException(Exception):
    """
    Base exception for all Cognitia errors.

    Attributes:
        message: Human-readable error message
        context: Additional context for debugging
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None):
        self.message = message
        self.context = context or {}
        super().__init__(message)

    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} ({context_str})"
        return self.message


# ============================================================================
# Component Lifecycle Exceptions
# ============================================================================

class ComponentException(CognitiaException):
    """Base class for component lifecycle errors."""
    pass


class ComponentInitializationError(ComponentException):
    """Component failed to initialize properly."""

    def __init__(self, component_name: str, reason: str):
        super().__init__(
            f"Failed to initialize {component_name}: {reason}",
            context={"component": component_name, "reason": reason}
        )
        self.component_name = component_name


class ComponentShutdownError(ComponentException):
    """Component failed to shutdown gracefully."""

    def __init__(self, component_name: str, reason: str):
        super().__init__(
            f"Failed to shutdown {component_name}: {reason}",
            context={"component": component_name, "reason": reason}
        )
        self.component_name = component_name


# ============================================================================
# Audio Exceptions
# ============================================================================

class AudioException(CognitiaException):
    """Base class for audio I/O errors."""
    pass


class AudioDeviceError(AudioException):
    """Hardware/device related audio error."""

    def __init__(self, device_name: str, reason: str):
        super().__init__(
            f"Audio device '{device_name}' error: {reason}",
            context={"device": device_name}
        )
        self.device_name = device_name


class VADException(AudioException):
    """Voice activity detection failed."""

    def __init__(self, reason: str):
        super().__init__(f"VAD error: {reason}")


class AudioBufferError(AudioException):
    """Audio buffer overflow or underflow."""

    def __init__(self, buffer_type: str, size: int, capacity: int):
        super().__init__(
            f"{buffer_type} buffer error: {size}/{capacity}",
            context={"type": buffer_type, "size": size, "capacity": capacity}
        )


# ============================================================================
# LLM Exceptions
# ============================================================================

class LLMException(CognitiaException):
    """Base class for LLM service errors."""
    pass


class LLMConnectionError(LLMException):
    """Cannot reach LLM service."""

    def __init__(self, url: str, original_error: Exception):
        super().__init__(
            f"Cannot connect to LLM service at {url}",
            context={"url": url, "original": str(original_error)}
        )
        self.url = url
        self.original_error = original_error


class LLMTimeoutError(LLMException):
    """LLM request exceeded timeout."""

    def __init__(self, timeout_seconds: float, url: str):
        super().__init__(
            f"LLM request to {url} exceeded {timeout_seconds}s timeout",
            context={"timeout": timeout_seconds, "url": url}
        )
        self.timeout_seconds = timeout_seconds
        self.url = url


class LLMResponseError(LLMException):
    """Invalid or unparseable LLM response."""

    def __init__(self, status_code: int, response_text: str, url: str):
        # Truncate long responses
        truncated = response_text[:200] + "..." if len(response_text) > 200 else response_text
        super().__init__(
            f"LLM HTTP {status_code} from {url}: {truncated}",
            context={"status_code": status_code, "url": url}
        )
        self.status_code = status_code
        self.response_text = response_text


class LLMStreamError(LLMException):
    """Error during streaming response processing."""

    def __init__(self, reason: str, partial_response: str | None = None):
        super().__init__(
            f"LLM stream error: {reason}",
            context={"partial_response": partial_response}
        )
        self.partial_response = partial_response


# ============================================================================
# Memory Exceptions
# ============================================================================

class MemoryException(CognitiaException):
    """Base class for memory system errors."""
    pass


class MemoryPersistenceError(MemoryException):
    """Failed to save or load memory."""

    def __init__(self, operation: str, path: str, reason: str):
        super().__init__(
            f"Memory {operation} failed for {path}: {reason}",
            context={"operation": operation, "path": path}
        )
        self.operation = operation
        self.path = path


class MemoryExtractionError(MemoryException):
    """Entity extraction failed."""

    def __init__(self, reason: str, conversation_text: str | None = None):
        super().__init__(
            f"Entity extraction failed: {reason}",
            context={"conversation": conversation_text[:100] if conversation_text else None}
        )


# ============================================================================
# Network Exceptions
# ============================================================================

class NetworkException(CognitiaException):
    """Base class for network communication errors."""
    pass


class ClientDisconnectError(NetworkException):
    """Client unexpectedly disconnected."""

    def __init__(self, client_address: str, reason: str | None = None):
        msg = f"Client {client_address} disconnected"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, context={"client": client_address})
        self.client_address = client_address


class NetworkTimeoutError(NetworkException):
    """Network operation timed out."""

    def __init__(self, operation: str, timeout_seconds: float):
        super().__init__(
            f"Network {operation} timed out after {timeout_seconds}s",
            context={"operation": operation, "timeout": timeout_seconds}
        )


class ProxyError(NetworkException):
    """Proxy connection failed."""

    def __init__(self, proxy_address: str, reason: str):
        super().__init__(
            f"Proxy {proxy_address} error: {reason}",
            context={"proxy": proxy_address}
        )


# ============================================================================
# Configuration Exceptions
# ============================================================================

class ConfigurationException(CognitiaException):
    """Base class for configuration errors."""
    pass


class ConfigValidationError(ConfigurationException):
    """Configuration validation failed."""

    def __init__(self, field: str, value: Any, reason: str):
        super().__init__(
            f"Invalid configuration for '{field}': {reason}",
            context={"field": field, "value": value}
        )
        self.field = field
        self.value = value


class ConfigFileError(ConfigurationException):
    """Cannot read configuration file."""

    def __init__(self, path: str, reason: str):
        super().__init__(
            f"Cannot load config from {path}: {reason}",
            context={"path": path}
        )
        self.path = path
