"""
loaders/trading_loader.py

Load dữ liệu giao dịch vào DB thông qua TradingRepository.
"""

from loguru import logger
from loaders.base_loader import BaseLoader
from db.repositories.trading_repo import TradingRepository


class TradingLoader:
    """Loader cho trading.* tables."""

    @staticmethod
    def load_foreign_flow(records: list[dict]) -> int:
        """Upsert foreign flow records."""
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = TradingRepository(conn)
            count = repo.upsert_foreign_flow(records)
            logger.debug("Loaded {} foreign flow records", count)
            return count
