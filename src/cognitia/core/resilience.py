"""
Resilience patterns for external service calls.

Implements circuit breaker and retry strategies to prevent
cascading failures.
"""

import random
import time
import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Any, TypeVar
from dataclasses import dataclass

from loguru import logger

T = TypeVar('T')


class CircuitState(str, Enum):
    """
    Circuit breaker states.

    State transitions:
        CLOSED -> OPEN (after failure_threshold failures)
        OPEN -> HALF_OPEN (after recovery_timeout)
        HALF_OPEN -> CLOSED (after success_threshold successes)
        HALF_OPEN -> OPEN (on any failure)
    """
    CLOSED = "closed"        # Normal operation, requests allowed
    OPEN = "open"           # Failing, reject requests immediately
    HALF_OPEN = "half_open" # Testing recovery, limited requests


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5      # Failures before opening
    recovery_timeout: float = 60.0  # Seconds before attempting recovery
    success_threshold: int = 2      # Successes to close from half-open
    name: str = "circuit"           # For logging


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, circuit_name: str, retry_after: float):
        self.circuit_name = circuit_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{circuit_name}' is OPEN. "
            f"Retry after {retry_after:.1f}s"
        )


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.

    Protects against cascading failures by temporarily rejecting
    requests when error rate exceeds threshold.

    Thread Safety:
        All state access protected by threading.Lock

    Example:
        >>> breaker = CircuitBreaker(CircuitBreakerConfig(
        ...     failure_threshold=3,
        ...     recovery_timeout=30.0
        ... ))
        >>>
        >>> try:
        ...     result = breaker.call(risky_function, arg1, arg2)
        ... except CircuitBreakerOpen:
        ...     # Handle circuit open
        ...     pass
    """

    def __init__(self, config: CircuitBreakerConfig):
        """
        Initialize circuit breaker.

        Args:
            config: Circuit breaker configuration
        """
        self.config = config

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._lock = threading.Lock()

        logger.info(
            f"[{config.name}] Circuit breaker initialized: "
            f"failure_threshold={config.failure_threshold}, "
            f"recovery_timeout={config.recovery_timeout}s"
        )

    @property
    def state(self) -> CircuitState:
        """
        Get current state (with automatic state transitions).

        Returns:
            Current circuit state

        Thread Safety:
            Protected by lock
        """
        with self._lock:
            # Check if we should transition from OPEN -> HALF_OPEN
            if self._state == CircuitState.OPEN and self._last_failure_time:
                time_since_failure = datetime.now() - self._last_failure_time
                if time_since_failure > timedelta(seconds=self.config.recovery_timeout):
                    logger.info(f"[{self.config.name}] Circuit transitioning to HALF_OPEN")
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0

            return self._state

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpen: If circuit is open
            Exception: Any exception from func (after recording)
        """
        current_state = self.state

        # Reject if circuit open
        if current_state == CircuitState.OPEN:
            with self._lock:
                retry_after = 0.0
                if self._last_failure_time:
                    elapsed = (datetime.now() - self._last_failure_time).total_seconds()
                    retry_after = max(0, self.config.recovery_timeout - elapsed)

            raise CircuitBreakerOpen(self.config.name, retry_after)

        # Attempt call
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Record successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(
                    f"[{self.config.name}] Success in HALF_OPEN "
                    f"({self._success_count}/{self.config.success_threshold})"
                )

                if self._success_count >= self.config.success_threshold:
                    logger.success(f"[{self.config.name}] Circuit closing (recovered)")
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                if self._failure_count > 0:
                    self._failure_count = 0

    def _on_failure(self) -> None:
        """Record failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN -> back to OPEN
                logger.warning(f"[{self.config.name}] Circuit re-opening (failed during recovery)")
                self._state = CircuitState.OPEN
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    logger.error(
                        f"[{self.config.name}] Circuit opening "
                        f"({self._failure_count} failures)"
                    )
                    self._state = CircuitState.OPEN

    def get_metrics(self) -> dict[str, Any]:
        """Get circuit breaker metrics."""
        with self._lock:
            return {
                "name": self.config.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure": self._last_failure_time.isoformat() if self._last_failure_time else None,
            }

    def reset(self) -> None:
        """Manually reset circuit to CLOSED state."""
        with self._lock:
            logger.info(f"[{self.config.name}] Circuit manually reset")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None


class RetryStrategy:
    """
    Exponential backoff retry strategy.

    Example:
        >>> retry = RetryStrategy(max_retries=3, initial_delay=0.1)
        >>> result = retry.execute(
        ...     risky_function,
        ...     retryable_exceptions=(ConnectionError,)
        ... )
    """

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        """
        Initialize retry strategy.

        Args:
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential backoff
            jitter: Add random jitter to delays
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    def execute(
        self,
        func: Callable[..., T],
        *args: Any,
        retryable_exceptions: tuple[type, ...] = (Exception,),
        **kwargs: Any
    ) -> T:
        """
        Execute function with retry logic.

        Args:
            func: Function to execute
            *args: Positional arguments
            retryable_exceptions: Exception types to retry on
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            Last exception if all retries exhausted
        """
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except retryable_exceptions as e:
                last_exception = e

                if attempt == self.max_retries:
                    logger.error(f"All {self.max_retries} retry attempts exhausted")
                    break

                # Calculate delay
                delay = min(
                    self.initial_delay * (self.exponential_base ** attempt),
                    self.max_delay
                )

                # Add jitter
                if self.jitter:
                    delay *= random.uniform(0.8, 1.2)

                logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries} failed: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                time.sleep(delay)

        # All retries exhausted
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError("Retry loop exited without exception")
