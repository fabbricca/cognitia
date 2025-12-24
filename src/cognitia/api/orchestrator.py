"""Orchestrator configuration helpers.

The GPU orchestrator is the only GPU-host service reachable from the cluster.
This module centralizes env var naming and defaults.
"""

from __future__ import annotations

import os


def get_orchestrator_url() -> str:
    """Return the base URL for the GPU orchestrator (no trailing slash)."""
    url = os.getenv(
        "COGNITIA_ORCHESTRATOR_URL",
        os.getenv("COGNITIA_CORE_URL", "http://10.0.0.15:8080"),
    )
    return url.rstrip("/")
