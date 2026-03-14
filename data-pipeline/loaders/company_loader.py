"""
loaders/company_loader.py

Load dữ liệu company vào DB thông qua CompanyRepository.
"""

from loguru import logger
from loaders.base_loader import BaseLoader
from db.repositories.company_repo import CompanyRepository


class CompanyLoader:
    """Loader cho company.* tables."""

    @staticmethod
    def load_profile(record: dict | None) -> None:
        """Insert company profile snapshot."""
        if record is None:
            return
        with BaseLoader.connect() as conn:
            repo = CompanyRepository(conn)
            repo.insert_profile(record)
            logger.debug("Loaded profile for {}", record.get("symbol"))

    @staticmethod
    def load_shareholders(records: list[dict]) -> int:
        """Upsert shareholders."""
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = CompanyRepository(conn)
            return repo.upsert_shareholders(records)

    @staticmethod
    def load_officers(records: list[dict]) -> int:
        """Upsert officers."""
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = CompanyRepository(conn)
            return repo.upsert_officers(records)

    @staticmethod
    def load_events(records: list[dict]) -> int:
        """Upsert events."""
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = CompanyRepository(conn)
            return repo.upsert_events(records)
