"""Signal tracker tests."""
import pytest


@pytest.mark.asyncio
async def test_log_and_resolve(patch_db):
    from services import signal_tracker
    sig_id = await signal_tracker.log_signal(
        user_id="u_track",
        ticker="AAPL",
        signal="BUY",
        confidence=72,
        strategy="trend_follow",
        timeframe="swing",
        regime="trending_bull",
    )
    assert sig_id

    res = await signal_tracker.resolve_signal(sig_id, "win", 3.2)
    assert res["status"] == "resolved"


@pytest.mark.asyncio
async def test_stats_aggregate(patch_db):
    from services import signal_tracker
    from database import db
    await db["signal_stats"].delete_many({"user_id": "u_stats"})

    # 3 wins, 1 loss for trend_follow
    for _ in range(3):
        sid = await signal_tracker.log_signal("u_stats", "AAPL", "BUY", 60, "trend_follow", "swing", "x")
        await signal_tracker.resolve_signal(sid, "win", 2)
    sid = await signal_tracker.log_signal("u_stats", "AAPL", "BUY", 60, "trend_follow", "swing", "x")
    await signal_tracker.resolve_signal(sid, "loss", -1)

    stats = await signal_tracker.get_stats("u_stats", "strategy")
    assert len(stats) >= 1
    tf = next((s for s in stats if s["key"] == "trend_follow"), None)
    assert tf is not None
    assert tf["wins"] == 3
    assert tf["losses"] == 1
    assert tf["win_rate"] == 75.0


@pytest.mark.asyncio
async def test_strategy_weights(patch_db):
    from services import signal_tracker
    from database import db
    await db["signal_stats"].delete_many({"user_id": "u_w"})

    # Build a record: 8 wins out of 10 for high_perf
    for _ in range(8):
        sid = await signal_tracker.log_signal("u_w", "AAPL", "BUY", 60, "high_perf", "swing", "x")
        await signal_tracker.resolve_signal(sid, "win", 2)
    for _ in range(2):
        sid = await signal_tracker.log_signal("u_w", "AAPL", "BUY", 60, "high_perf", "swing", "x")
        await signal_tracker.resolve_signal(sid, "loss", -1)

    weights = await signal_tracker.get_strategy_weights("u_w")
    assert weights.get("high_perf", 0) > 1.0


@pytest.mark.asyncio
async def test_resolve_invalid_id(patch_db):
    from services import signal_tracker
    res = await signal_tracker.resolve_signal("not-an-id", "win", 0)
    assert "error" in res
