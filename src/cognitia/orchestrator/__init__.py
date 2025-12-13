"""
Cognitia Orchestrator - HTTP/WebSocket interface for the Core.

This module provides a simple, clean interface between the K8s entrance
and the GPU-based core processing. No authentication - all requests are trusted.
"""

from .server import app, run_server

__all__ = ["app", "run_server"]
