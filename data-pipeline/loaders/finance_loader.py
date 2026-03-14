"""
loaders/finance_loader.py

Load dữ liệu BCTC (EAV) vào DB thông qua FinanceRepository.
"""

from loguru import logger
from loaders.base_loader import BaseLoader
from db.repositories.finance_repo import FinanceRepository


class FinanceLoader:
    """Loader cho finance.* tables (EAV format)."""

    @staticmethod
    def load_income_statement(records: list[dict]) -> int:
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = FinanceRepository(conn)
            count = repo.upsert_income_statement(records)
            logger.debug("Loaded {} income statement records", count)
            return count

    @staticmethod
    def load_balance_sheet(records: list[dict]) -> int:
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = FinanceRepository(conn)
            count = repo.upsert_balance_sheet(records)
            logger.debug("Loaded {} balance sheet records", count)
            return count

    @staticmethod
    def load_cash_flow(records: list[dict]) -> int:
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = FinanceRepository(conn)
            count = repo.upsert_cash_flow(records)
            logger.debug("Loaded {} cash flow records", count)
            return count

    @staticmethod
    def load_financial_ratios(records: list[dict]) -> int:
        if not records:
            return 0
        with BaseLoader.connect() as conn:
            repo = FinanceRepository(conn)
            count = repo.upsert_financial_ratios(records)
            logger.debug("Loaded {} financial ratio records", count)
            return count
