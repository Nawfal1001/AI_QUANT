"""Auth tests."""
import pytest


@pytest.mark.asyncio
async def test_register_creates_user(patch_db):
    from services.auth_service import register
    res = await register("alice@example.com", "password123", "alice")
    assert "access_token" in res
    assert res["user"]["username"] == "alice"
    assert res["user"]["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_register_rejects_short_password(patch_db):
    from services.auth_service import register
    res = await register("bob@example.com", "short", "bob")
    assert "error" in res


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(patch_db):
    from services.auth_service import register
    from database import db
    await db["users"].delete_many({})
    await register("dup@example.com", "password123", "dup1")
    res = await register("dup@example.com", "password123", "dup2")
    # Returns a generic error so attackers can't enumerate accounts.
    assert "error" in res


@pytest.mark.asyncio
async def test_first_user_admin_requires_bootstrap_flag(patch_db, monkeypatch):
    """Without ALLOW_ADMIN_BOOTSTRAP=true, a fresh DB does NOT silently grant admin."""
    from services.auth_service import register
    from database import db
    await db["users"].delete_many({})
    await db["admin_bootstrap"].delete_many({})
    monkeypatch.delenv("ALLOW_ADMIN_BOOTSTRAP", raising=False)
    res = await register("first@example.com", "password123", "firstx")
    assert res["user"]["role"] == "user"


@pytest.mark.asyncio
async def test_admin_bootstrap_when_flag_enabled(patch_db, monkeypatch):
    """With ALLOW_ADMIN_BOOTSTRAP=true, the first registrant is admin (atomically)."""
    from services.auth_service import register
    from database import db
    await db["users"].delete_many({})
    await db["admin_bootstrap"].delete_many({})
    monkeypatch.setenv("ALLOW_ADMIN_BOOTSTRAP", "true")
    res = await register("boot@example.com", "password123", "bootx")
    assert res["user"]["role"] == "admin"
    res2 = await register("second2@example.com", "password123", "secondx")
    assert res2["user"]["role"] == "user"


@pytest.mark.asyncio
async def test_login_success(patch_db):
    from services.auth_service import register, login
    from database import db
    await db["users"].delete_many({})
    await register("login@example.com", "password123", "loginuser")
    res = await login("login@example.com", "password123")
    assert "access_token" in res
    assert res["user"]["username"] == "loginuser"


@pytest.mark.asyncio
async def test_login_wrong_password(patch_db):
    from services.auth_service import register, login
    from database import db
    await db["users"].delete_many({})
    await register("wrong@example.com", "password123", "wrong")
    res = await login("wrong@example.com", "badpass")
    assert "error" in res
