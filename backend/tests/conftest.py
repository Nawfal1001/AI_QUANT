"""
Pytest fixtures.

Uses mongomock-motor for an in-memory DB and FastAPI TestClient for E2E tests.
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Configure env BEFORE importing any app code
os.environ.setdefault("JWT_SECRET", "test_" + "x" * 48)
os.environ.setdefault("DB_NAME", "tradeai_test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture(scope="session", autouse=True)
def patch_db():
    """Patch the database module to use mongomock-motor if available."""
    try:
        from mongomock_motor import AsyncMongoMockClient
        client = AsyncMongoMockClient()
        import database
        database.db = client[os.getenv("DB_NAME", "tradeai_test")]
        database.client = client
    except ImportError:
        pass
    yield


@pytest.fixture
async def test_user():
    """Create a test user via the service layer."""
    from services.auth_service import register
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    res = await register(email, "password123", f"user_{uuid.uuid4().hex[:6]}")
    return res["user"], res["access_token"]


@pytest.fixture
async def admin_user():
    from database import db
    await db["users"].delete_many({})
    from services.auth_service import register
    res = await register("admin@example.com", "adminpass123", "admin")
    return res["user"], res["access_token"]


# ============================================================
# E2E fixtures — use FastAPI TestClient against the live app
# ============================================================

@pytest.fixture(scope="module")
def app_client():
    """Module-scoped FastAPI TestClient."""
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        yield client


@pytest.fixture
def e2e_user(app_client):
    """Register a fresh user via the HTTP API and return (user, token)."""
    import uuid
    suffix = uuid.uuid4().hex[:6]
    res = app_client.post("/api/auth/register", json={
        "email": f"e2e_{suffix}@example.com",
        "password": "password123",
        "username": f"e2e_{suffix}",
    })
    assert res.status_code == 200, res.text
    data = res.json()
    return data["user"], data["access_token"]


@pytest.fixture
def auth_headers(e2e_user):
    _, token = e2e_user
    return {"Authorization": f"Bearer {token}"}
