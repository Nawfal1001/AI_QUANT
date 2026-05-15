"""
Broker adapter base class.

Every concrete adapter (Alpaca, Binance, OANDA) implements this interface so
the order router can call them uniformly. Each call returns a normalized dict
or raises BrokerError.
"""
from abc import ABC, abstractmethod
from typing import Optional


class BrokerError(Exception):
    """Raised when a broker call fails for a recoverable reason."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class BrokerAdapter(ABC):
    """
    All methods are async.
    Concrete classes accept a dict of credentials in __init__ and a
    paper_mode flag (where supported).
    """

    name: str = "base"

    def __init__(self, credentials: dict, paper_mode: bool = True):
        self.credentials = credentials
        self.paper_mode = paper_mode

    @abstractmethod
    async def test_connection(self) -> dict:
        """Returns {"status": "connected"|"auth_failed"|"test_failed", "balance": float, "message": str}"""

    @abstractmethod
    async def get_balance(self) -> float:
        """Cash balance in account currency."""

    @abstractmethod
    async def place_order(
        self,
        ticker: str,
        side: str,           # "buy" or "sell"
        qty: float,
        order_type: str = "market",  # "market" or "limit"
        limit_price: Optional[float] = None,
        time_in_force: str = "gtc",
    ) -> dict:
        """
        Returns {
          "broker_order_id": str,
          "status": "submitted"|"filled"|"rejected",
          "filled_qty": float,
          "fill_price": Optional[float],
          "message": str,
        }
        """

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> dict:
        """Returns {"status": "cancelled"|"error", "message": str}"""

    @abstractmethod
    async def get_positions(self) -> list:
        """Returns list of {"ticker": str, "qty": float, "avg_entry": float, "market_value": float}"""

    @abstractmethod
    async def get_order(self, broker_order_id: str) -> dict:
        """Returns current status of a previously-placed order."""
