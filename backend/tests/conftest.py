"""Pytest fixtures for backend tests."""
import os
import pytest

# Avoid loading real env; use test values
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake")
os.environ.setdefault("CLIENT_ID", "default")


@pytest.fixture
def client():
    """FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)
