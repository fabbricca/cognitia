"""Cognitia REST API.

Keep this package import side-effect free: importing `cognitia.api.*` should not
import and initialize the full FastAPI app.
"""

__all__ = ["create_app"]


def create_app():
	from .main import create_app as _create_app

	return _create_app()
