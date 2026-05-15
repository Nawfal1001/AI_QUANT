from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
load_dotenv()
MONGO_URL = os.getenv("MONGO_URL","mongodb+srv://nawfal1001:Nawfal1001%21@cluster0.1els7ds.mongodb.net/?appName=Cluster0")
DB_NAME   = os.getenv("DB_NAME","tradeai_db")
client = AsyncIOMotorClient(MONGO_URL)
db     = client[DB_NAME]
async def create_indexes():
    await db["users"].create_index("email",unique=True)
    await db["users"].create_index("username",unique=True)
    await db["signals_log"].create_index([("ticker",1),("timestamp",-1)])
    await db["signals_log"].create_index("outcome")
    await db["open_trades"].create_index("status")
    await db["trade_history"].create_index("closed_at")
    await db["portfolio"].create_index("ticker",unique=True)
    print("[DB] Indexes OK")
