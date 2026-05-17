"""Client for ASI-Evolve hosted externally, e.g. Google Colab/ngrok.
The backend never stores ASI code here; it sends strategy/backtest context to the configured ASI endpoint
and receives proposed parameter or strategy mutations.
"""
import os
import httpx
from services.logger import child

log = child("asi_evolve")


def _base_url() -> str:
    return (os.getenv("ASI_EVOLVE_URL") or os.getenv("ASI_COLAB_URL") or "").rstrip("/")


def _token() -> str:
    return os.getenv("ASI_EVOLVE_TOKEN") or os.getenv("ASI_COLAB_TOKEN") or ""


def enabled() -> bool:
    return bool(_base_url())


async def health():
    if not enabled():
        return {"enabled": False, "status": "not_configured"}
    try:
        headers = {"Authorization": f"Bearer {_token()}"} if _token() else {}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{_base_url()}/health", headers=headers)
            r.raise_for_status()
            return {"enabled": True, "status": "ok", "remote": r.json()}
    except Exception as e:
        log.warning(f"ASI health failed: {e}")
        return {"enabled": True, "status": "error", "error": str(e)}


async def evolve(payload: dict, timeout: int = 120):
    if not enabled():
        return {"error": "ASI_EVOLVE_URL not configured"}
    headers = {"Authorization": f"Bearer {_token()}"} if _token() else {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{_base_url()}/evolve", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning(f"ASI evolve failed: {e}")
        return {"error": str(e)}
