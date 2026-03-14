"""
loaders/market_loader.py

Load dữ liệu OHLCV vào DB thông qua MarketRepository.
"""

from loguru import logger
from loaders.base_loader import BaseLoader
from db.repositories.market_repo import MarketRepository


class MarketLoader:
    """Loader cho market.ohlcv_daily."""

    @staticmethod
    def load_ohlcv_daily(records: list[dict]) -> int:
        """Upsert OHLCV daily records vào market.ohlcv_daily."""
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = MarketRepository(conn)
            count = repo.upsert_ohlcv_daily(records)
            logger.debug("Loaded {} OHLCV daily records", count)
            return count

    @staticmethod
    def get_latest_date(symbol: str, interval: str = "1D") -> str | None:
        """Lấy ngày OHLCV mới nhất đã có trong DB."""
        with BaseLoader.connect() as conn:
            repo = MarketRepository(conn)
            return repo.get_latest_ohlcv_date(symbol, interval)
