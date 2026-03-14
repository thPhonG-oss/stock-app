"""
loaders/listing_loader.py

Load dữ liệu listing vào DB thông qua ListingRepository.
"""

from loguru import logger
from loaders.base_loader import BaseLoader
from db.repositories.listing_repo import ListingRepository


class ListingLoader:
    """Loader cho listing.symbol và listing.icb_industry."""

    @staticmethod
    def load_symbols(records: list[dict]) -> int:
        """Upsert danh sách symbols vào listing.symbol."""
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = ListingRepository(conn)
            count = repo.upsert_symbols(records)
            logger.info("Loaded {} symbols vào DB", count)
            return count

    @staticmethod
    def load_icb_industries(records: list[dict]) -> int:
        """Upsert ICB industries vào listing.icb_industry."""
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = ListingRepository(conn)
            count = repo.upsert_icb_industries(records)
            logger.info("Loaded {} ICB records vào DB", count)
            return count
