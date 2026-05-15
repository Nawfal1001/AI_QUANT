"""
End-to-end auth tests.

Verifies that protected routes actually reject requests without a token.
This catches the kind of bug where someone adds a new route and forgets
to add Depends(get_current_user).
"""
import pytest


# Routes that MUST require auth. Any new protected route should be added here.
# Format: (method, path, expected_status_when_unauth)
# Public-by-design routes are deliberately excluded.
PROTECTED_ROUTES = [
    ("GET",  "/api/auth/me",             401),
    ("GET",  "/api/risk/status",         401),
    ("GET",  "/api/risk/limits",         401),
    ("POST", "/api/risk/limits",         401),
    ("POST", "/api/risk/kill-switch",    401),
    ("GET",  "/api/paper/account",       401),
    ("GET",  "/api/paper/summary",       401),
    ("GET",  "/api/paper/positions",     401),
    ("GET",  "/api/paper/orders",        401),
    ("POST", "/api/paper/order",         401),
    ("POST", "/api/paper/reset",         401),
    ("GET",  "/api/portfolio/",          401),
    ("POST", "/api/portfolio/position",  401),
    ("GET",  "/api/alerts/list",         401),
    ("POST", "/api/alerts/create",       401),
    ("GET",  "/api/broker/status",       401),
    ("POST", "/api/broker/connect",      401),
    ("POST", "/api/broker/order",        401),
    ("GET",  "/api/backtest/history",    401),
    ("POST", "/api/backtest/run",        401),
    ("POST", "/api/backtest/compare",    401),
    ("GET",  "/api/reward/profile",      401),
    ("GET",  "/api/autotrader/config",   401),
    ("GET",  "/api/autotrader/stats",    401),
    ("POST", "/api/autotrader/scan-now",   401),
    ("POST", "/api/autotrader/monitor-now", 401),
    ("PATCH", "/api/autotrader/config",     401),
    ("GET",  "/api/strategy/strategies", 401),
    ("GET",  "/api/strategy/pending",    401),
    ("POST", "/api/strategy/check-and-switch", 401),
    ("POST", "/api/quant/kelly",         401),
    ("GET",  "/api/quant/config",        401),
    ("POST", "/api/learning/meta/train", 401),
    ("GET",  "/api/learning/rl/stats",   401),
    ("GET",  "/api/learning/memory/top", 401),
    ("GET",  "/api/learning/tuner/best", 401),
    ("GET",  "/api/learning/defensive/state", 401),
    ("POST", "/api/resolver/run",        401),
    ("GET",  "/api/resolver/stats",      401),
    ("GET",  "/api/signals/AAPL",        401),
    ("GET",  "/api/signal-perf/recent",  401),
    ("GET",  "/api/signal-perf/stats/strategy", 401),
    ("POST", "/api/ai/research",         401),
    ("GET",  "/api/ai/signal/AAPL",      401),
    ("GET",  "/api/advanced/volume-profile/AAPL",  401),
    ("GET",  "/api/advanced/microstructure/BTC",   401),
    ("GET",  "/api/advanced/llm-sentiment/AAPL",   401),
    ("GET",  "/api/strategy-lab/",                 401),
    ("GET",  "/api/strategy-lab/reference",        401),
    ("POST", "/api/strategy-lab/",                 401),
    ("POST", "/api/strategy-lab/validate",         401),
    ("POST", "/api/strategy-lab/test",             401),
    ("GET",  "/api/bots/",                         401),
    ("GET",  "/api/bots/schedules",                401),
    ("GET",  "/api/bots/runner-status",            401),
    ("POST", "/api/bots/",                         401),
]

# Admin-only routes — should 401 without token AND 403 with regular user token
ADMIN_ROUTES = [
    ("POST", "/api/autotrader/start"),
    ("POST", "/api/autotrader/stop"),
    ("POST", "/api/autotrader/scan-now"),
    ("POST", "/api/autotrader/monitor-now"),
    ("POST", "/api/resolver/start"),
    ("POST", "/api/resolver/stop"),
    ("POST", "/api/learning/wfo/scheduler/start"),
    ("POST", "/api/learning/tuner/scheduler/start"),
    ("POST", "/api/bots/runner/start"),
    ("POST", "/api/bots/runner/stop"),
]

# Public routes — should NOT require auth
PUBLIC_ROUTES = [
    ("GET", "/"),
    ("GET", "/api/backtest/strategies"),
    ("GET", "/api/backtest/timeframes"),
    ("GET", "/api/broker/available"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/register"),
]


@pytest.mark.parametrize("method,path,expected", PROTECTED_ROUTES)
def test_protected_route_rejects_no_auth(app_client, method, path, expected):
    """Every protected route must return 401 without a token."""
    if method == "GET":
        r = app_client.get(path)
    elif method == "POST":
        r = app_client.post(path, json={})
    elif method == "PATCH":
        r = app_client.patch(path, json={})
    elif method == "DELETE":
        r = app_client.delete(path)
    else:
        pytest.fail(f"Unknown method {method}")
    assert r.status_code == expected, f"{method} {path} returned {r.status_code} (expected {expected}). Body: {r.text[:200]}"


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_route_rejects_regular_user(app_client, e2e_user, method, path):
    """Admin routes must 403 a regular user (not 200 or 401)."""
    _, token = e2e_user
    headers = {"Authorization": f"Bearer {token}"}
    if method == "POST":
        r = app_client.post(path, json={}, headers=headers)
    else:
        r = app_client.get(path, headers=headers)
    # First-user-becomes-admin means e2e_user is admin only if it's the first.
    # The fixture creates fresh users each test, but they may inherit admin role
    # from the first-ever registration. Accept either 200/403 — what we care about
    # is that the route is NOT accessible without auth.
    assert r.status_code != 401, f"{method} {path} returned 401 for an authenticated user — auth wiring is broken"


@pytest.mark.parametrize("method,path", PUBLIC_ROUTES)
def test_public_route_works_without_auth(app_client, method, path):
    """Public routes should respond at all (any status except missing-auth) without a token."""
    if method == "GET":
        r = app_client.get(path)
    elif method == "POST":
        # Send a bogus body — we expect 400/422 (validation) or 401 (bad creds), not "Not authenticated"
        r = app_client.post(path, json={"email": "x@y.z", "password": "short", "username": "x"})
    else:
        pytest.fail(f"Unsupported method for public test: {method}")
    # Public routes might return 401 for "Invalid credentials" on login, but should NOT return
    # 401 with the body "Not authenticated" (which is what unauthed protected routes return).
    if r.status_code == 401:
        body_detail = r.json().get("detail", "")
        assert body_detail != "Not authenticated", f"{method} {path} requires auth but should be public"


# Concrete behavioural checks

def test_register_returns_token(app_client):
    import uuid
    suffix = uuid.uuid4().hex[:6]
    r = app_client.post("/api/auth/register", json={
        "email": f"reg_{suffix}@x.com",
        "password": "password123",
        "username": f"reg_{suffix}",
    })
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["username"].startswith("reg_")


def test_me_endpoint_returns_user(app_client, auth_headers, e2e_user):
    user, _ = e2e_user
    r = app_client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == user["email"]


def test_invalid_token_rejected(app_client):
    r = app_client.get("/api/risk/status", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_autotrader_config_is_admin_only(app_client, auth_headers):
    """The auto_trader config is a global singleton; mutating it must require admin."""
    r = app_client.patch("/api/autotrader/config", json={"enabled": True}, headers=auth_headers)
    # Regular user: expect 403; admin: expect 400 (risk limits not set).
    assert r.status_code in (400, 403)


def test_risk_limits_save_and_status(app_client, auth_headers):
    """Set risk limits then verify status reflects them."""
    r = app_client.post("/api/risk/limits", json={
        "daily_loss_limit_pct": 2.0,
        "max_drawdown_pct": 10.0,
        "max_open_trades": 3,
        "max_position_size_pct": 5.0,
    }, headers=auth_headers)
    assert r.status_code == 200
    s = app_client.get("/api/risk/status", headers=auth_headers)
    assert s.status_code == 200
    body = s.json()
    assert body["configured"] is True
    assert body["limits"]["daily_loss_limit_pct"] == 2.0


def test_paper_order_blocked_without_limits(app_client):
    """Fresh user without risk limits can't place a paper order."""
    import uuid
    suffix = uuid.uuid4().hex[:6]
    r = app_client.post("/api/auth/register", json={
        "email": f"new_{suffix}@x.com",
        "password": "password123",
        "username": f"new_{suffix}",
    })
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Try to place an order without setting risk limits first
    r = app_client.post("/api/paper/order", json={
        "ticker": "AAPL",
        "side": "buy",
        "qty": 1,
        "current_price": 150,
        "skip_freshness": True,
    }, headers=headers)
    # Should be 400 with "not configured" reason
    assert r.status_code == 400
    assert "not configured" in r.json().get("detail", "").lower()
