from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv()

# Fail-closed: never silently fall back to localhost or to a hardcoded secret.
# Tests set MONGO_URL via conftest.py before importing this module.
MONGO_URL = os.getenv("MONGO_URL", "")
if not MONGO_URL:
    raise RuntimeError(
        "MONGO_URL not configured. Set it in environment or .env. "
        "Never commit DB credentials to source."
    )
DB_NAME = os.getenv("DB_NAME", "tradeai_db")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def create_indexes():
    await db["users"].create_index("email", unique=True)
    await db["users"].create_index("username", unique=True)
    await db["signals_log"].create_index([("ticker", 1), ("timestamp", -1)])
    await db["signals_log"].create_index("outcome")
    await db["open_trades"].create_index("status")
    await db["trade_history"].create_index("closed_at")
    # Compound (user_id, ticker) so two users can hold the same ticker.
    await db["portfolio"].create_index([("user_id", 1), ("ticker", 1)], unique=True)
    await db["brokers"].create_index([("user_id", 1), ("broker_id", 1)], unique=True)
    await db["live_orders"].create_index([("user_id", 1), ("submitted_at", -1)])
    await db["live_orders"].create_index([("user_id", 1), ("broker_id", 1), ("broker_order_id", 1)])
    await db["bots"].create_index([("user_id", 1), ("enabled", 1), ("next_run_at", 1)])
    await db["bot_executions"].create_index([("user_id", 1), ("bot_id", 1), ("started_at", -1)])
    print("[DB] Indexes OK")
