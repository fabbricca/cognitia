from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import cognitia


@lru_cache(maxsize=1)
def get_package_root() -> Path:
    """Return the workspace root (cached).

    This mirrors the old layout: src/cognitia -> src -> project_root.
    """
    package_dir = Path(os.path.dirname(os.path.abspath(cognitia.__file__)))
    return package_dir.parent.parent


def resource_path(relative_path: str) -> Path:
    """Return absolute path to a resource/model file.

    If `COGNITIA_RESOURCES_ROOT` is set, it is used as the base directory.
    Otherwise the package root is used.

    `relative_path` is expected to look like `models/TTS/...` or `models/ASR/...`.
    """
    base = Path(os.getenv("COGNITIA_RESOURCES_ROOT", str(get_package_root())))
    return base / relative_path
