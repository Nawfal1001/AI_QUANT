"""
Centralized structured logger.
- Writes to logs/tradeai.log (rotating, 10MB x 5 backups)
- Also prints to console
- Use: from services.logger import log; log.info("msg") / log.warning / log.error / log.exception
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

os.makedirs(LOG_DIR, exist_ok=True)


def _build_logger():
    logger = logging.getLogger("tradeai")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, "tradeai.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


log = _build_logger()


def child(name: str) -> logging.Logger:
    """Return a child logger e.g. log_auto = child('auto_trader')."""
    return log.getChild(name)
