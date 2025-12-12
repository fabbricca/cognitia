"""
Base component architecture for Cognitia.

Provides lifecycle management, state tracking, and health monitoring
for all Cognitia components.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
import threading
import time

from loguru import logger

from .exceptions import ComponentInitializationError, ComponentShutdownError


class ComponentState(str, Enum):
    """
    Component lifecycle states.

    State transitions:
        INITIALIZING -> RUNNING -> SHUTDOWN
        INITIALIZING -> ERROR
        RUNNING -> PAUSED -> RUNNING
        RUNNING -> ERROR -> RUNNING (after recovery)
    """
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    SHUTDOWN = "shutdown"
    ERROR = "error"


@dataclass
class ComponentMetrics:
    """
    Performance and health metrics for a component.

    Attributes:
        started_at: When component was initialized
        processed_items: Count of items processed (messages, audio frames, etc.)
        errors: Count of errors encountered
        last_activity: Most recent processing timestamp
        custom_metrics: Component-specific metrics
    """
    started_at: datetime = field(default_factory=datetime.now)
    processed_items: int = 0
    errors: int = 0
    last_activity: datetime = field(default_factory=datetime.now)
    custom_metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def uptime_seconds(self) -> float:
        """Calculate uptime in seconds."""
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def items_per_second(self) -> float:
        """Calculate average processing rate."""
        uptime = self.uptime_seconds
        if uptime < 0.001:  # Avoid division by zero
            return 0.0
        return self.processed_items / uptime

    @property
    def error_rate(self) -> float:
        """Calculate error percentage."""
        total = self.processed_items + self.errors
        if total == 0:
            return 0.0
        return (self.errors / total) * 100


class Component(ABC):
    """
    Abstract base class for all Cognitia components.

    Provides:
    - Standardized lifecycle (initialize, run, shutdown)
    - State management
    - Health monitoring
    - Metrics collection
    - Thread safety

    Subclasses must implement:
    - _initialize_impl()
    - _run_impl()
    - _shutdown_impl()
    """

    def __init__(self, name: str):
        """
        Initialize component base.

        Args:
            name: Human-readable component name for logging
        """
        self.name = name
        self._state = ComponentState.INITIALIZING
        self._state_lock = threading.RLock()
        self._metrics = ComponentMetrics()
        self._metrics_lock = threading.RLock()

        # Events for coordination
        self._shutdown_event = threading.Event()
        self._pause_event = threading.Event()

        logger.info(f"[{self.name}] Component created")

    # ========================================================================
    # Public API
    # ========================================================================

    def initialize(self) -> None:
        """
        Initialize component resources.

        Raises:
            ComponentInitializationError: If initialization fails
        """
        with self._state_lock:
            if self._state != ComponentState.INITIALIZING:
                raise ComponentInitializationError(
                    self.name,
                    f"Cannot initialize from state {self._state}"
                )

            try:
                logger.info(f"[{self.name}] Initializing...")
                self._initialize_impl()
                self._state = ComponentState.RUNNING
                logger.success(f"[{self.name}] Initialized successfully")
            except Exception as e:
                self._state = ComponentState.ERROR
                raise ComponentInitializationError(
                    self.name,
                    f"Initialization failed: {e}"
                ) from e

    def run(self) -> None:
        """
        Start component main loop.

        This method blocks until shutdown is requested.
        """
        with self._state_lock:
            if self._state != ComponentState.RUNNING:
                raise ComponentInitializationError(
                    self.name,
                    f"Cannot run from state {self._state}. Must initialize first."
                )

        logger.info(f"[{self.name}] Starting main loop")

        try:
            self._run_impl()
        except Exception as e:
            logger.exception(f"[{self.name}] Unexpected error in main loop: {e}")
            with self._state_lock:
                self._state = ComponentState.ERROR
            raise
        finally:
            logger.info(f"[{self.name}] Main loop exited")

    def shutdown(self, timeout: float = 5.0) -> None:
        """
        Gracefully shutdown component.

        Args:
            timeout: Maximum time to wait for shutdown in seconds

        Raises:
            ComponentShutdownError: If shutdown fails or times out
        """
        logger.info(f"[{self.name}] Shutdown requested")

        with self._state_lock:
            if self._state == ComponentState.SHUTDOWN:
                logger.warning(f"[{self.name}] Already shutdown")
                return

            self._shutdown_event.set()

        # Wait for graceful shutdown
        start_time = time.time()
        try:
            self._shutdown_impl()

            with self._state_lock:
                self._state = ComponentState.SHUTDOWN

            elapsed = time.time() - start_time
            logger.success(f"[{self.name}] Shutdown complete ({elapsed:.2f}s)")

        except Exception as e:
            raise ComponentShutdownError(
                self.name,
                f"Shutdown failed: {e}"
            ) from e

    def pause(self) -> None:
        """Pause component processing."""
        with self._state_lock:
            if self._state == ComponentState.RUNNING:
                self._state = ComponentState.PAUSED
                self._pause_event.set()
                logger.info(f"[{self.name}] Paused")

    def resume(self) -> None:
        """Resume component processing."""
        with self._state_lock:
            if self._state == ComponentState.PAUSED:
                self._state = ComponentState.RUNNING
                self._pause_event.clear()
                logger.info(f"[{self.name}] Resumed")

    # ========================================================================
    # State & Metrics
    # ========================================================================

    @property
    def state(self) -> ComponentState:
        """Get current component state (thread-safe)."""
        with self._state_lock:
            return self._state

    @property
    def is_running(self) -> bool:
        """Check if component is running."""
        return self.state == ComponentState.RUNNING

    @property
    def is_healthy(self) -> bool:
        """
        Check component health.

        Default implementation checks:
        - State is RUNNING or PAUSED
        - Last activity within 30 seconds

        Override for custom health checks.
        """
        with self._state_lock:
            if self._state not in (ComponentState.RUNNING, ComponentState.PAUSED):
                return False

        with self._metrics_lock:
            idle_time = (datetime.now() - self._metrics.last_activity).total_seconds()
            return idle_time < 30.0

    def get_metrics(self) -> ComponentMetrics:
        """Get current metrics snapshot (thread-safe)."""
        with self._metrics_lock:
            # Return a copy to prevent external modification
            return ComponentMetrics(
                started_at=self._metrics.started_at,
                processed_items=self._metrics.processed_items,
                errors=self._metrics.errors,
                last_activity=self._metrics.last_activity,
                custom_metrics=self._metrics.custom_metrics.copy(),
            )

    def get_status_summary(self) -> dict[str, Any]:
        """Get human-readable status summary."""
        metrics = self.get_metrics()
        return {
            "name": self.name,
            "state": self.state.value,
            "healthy": self.is_healthy,
            "uptime_seconds": metrics.uptime_seconds,
            "processed_items": metrics.processed_items,
            "errors": metrics.errors,
            "error_rate_percent": metrics.error_rate,
            "items_per_second": metrics.items_per_second,
        }

    # ========================================================================
    # Protected helpers for subclasses
    # ========================================================================

    def _record_activity(self, items_processed: int = 1) -> None:
        """Record processing activity (call from subclass)."""
        with self._metrics_lock:
            self._metrics.processed_items += items_processed
            self._metrics.last_activity = datetime.now()

    def _record_error(self) -> None:
        """Record error occurrence (call from subclass)."""
        with self._metrics_lock:
            self._metrics.errors += 1

    def _set_custom_metric(self, key: str, value: Any) -> None:
        """Set component-specific metric."""
        with self._metrics_lock:
            self._metrics.custom_metrics[key] = value

    def _should_shutdown(self) -> bool:
        """Check if shutdown was requested."""
        return self._shutdown_event.is_set()

    def _is_paused(self) -> bool:
        """Check if component is paused."""
        return self._pause_event.is_set()

    # ========================================================================
    # Abstract methods - subclasses must implement
    # ========================================================================

    @abstractmethod
    def _initialize_impl(self) -> None:
        """
        Component-specific initialization logic.

        Called by initialize(). Should set up resources, validate config, etc.

        Raises:
            Exception: Any exception will be wrapped in ComponentInitializationError
        """
        pass

    @abstractmethod
    def _run_impl(self) -> None:
        """
        Component-specific main loop logic.

        Called by run(). Should contain the main processing loop.
        Must periodically check _should_shutdown() and exit gracefully.

        Raises:
            Exception: Any exception will be logged and bubble up
        """
        pass

    @abstractmethod
    def _shutdown_impl(self) -> None:
        """
        Component-specific shutdown logic.

        Called by shutdown(). Should clean up resources, close connections, etc.

        Raises:
            Exception: Any exception will be wrapped in ComponentShutdownError
        """
        pass
