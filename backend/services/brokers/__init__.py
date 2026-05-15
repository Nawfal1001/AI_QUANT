"""Broker adapter package."""
from services.brokers.base import BrokerAdapter, BrokerError
from services.brokers.alpaca import AlpacaAdapter
from services.brokers.binance import BinanceAdapter
from services.brokers.oanda import OandaAdapter


ADAPTERS = {
    "alpaca": AlpacaAdapter,
    "binance": BinanceAdapter,
    "oanda": OandaAdapter,
}


def make_adapter(broker_id: str, credentials: dict, paper_mode: bool = True) -> BrokerAdapter:
    """Factory — create the right adapter for the given broker_id."""
    if broker_id not in ADAPTERS:
        raise BrokerError(f"Unsupported broker: {broker_id}")
    return ADAPTERS[broker_id](credentials, paper_mode=paper_mode)


__all__ = ["BrokerAdapter", "BrokerError", "make_adapter", "ADAPTERS"]
