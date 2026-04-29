"""
ASGI application entry for process managers and tests.

Usage: uvicorn app_factory:app --host 0.0.0.0 --port 8000
(Equivalent to: uvicorn main:app)
"""

from __future__ import annotations

# Re-export the FastAPI instance built in main (single source of truth for routes and lifespan).
from main import app  # noqa: F401

__all__ = ["app"]
