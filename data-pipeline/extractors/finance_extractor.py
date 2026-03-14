"""
extractors/finance_extractor.py

Trích xuất báo cáo tài chính từ vnstock Finance API.
"""

import pandas as pd
from loguru import logger
from sources.vnstock_source import VnstockSource


class FinanceExtractor:
    """Gọi vnstock Finance API để lấy BCTC."""

    @staticmethod
    def extract_income_statement(symbol: str, period: str = "quarter") -> pd.DataFrame:
        """Lấy báo cáo kết quả kinh doanh."""
        logger.debug("Extracting income statement: {} (period={})", symbol, period)
        client = VnstockSource.finance(symbol, period=period)
        df = client.income_statement(period=period, lang="en")
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def extract_balance_sheet(symbol: str, period: str = "quarter") -> pd.DataFrame:
        """Lấy bảng cân đối kế toán."""
        logger.debug("Extracting balance sheet: {} (period={})", symbol, period)
        client = VnstockSource.finance(symbol, period=period)
        df = client.balance_sheet(period=period, lang="en")
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def extract_cash_flow(symbol: str, period: str = "quarter") -> pd.DataFrame:
        """Lấy báo cáo lưu chuyển tiền tệ."""
        logger.debug("Extracting cash flow: {} (period={})", symbol, period)
        client = VnstockSource.finance(symbol, period=period)
        df = client.cash_flow(period=period, lang="en")
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def extract_ratio(symbol: str, period: str = "quarter") -> pd.DataFrame:
        """Lấy chỉ số tài chính."""
        logger.debug("Extracting financial ratios: {} (period={})", symbol, period)
        client = VnstockSource.finance(symbol, period=period)
        df = client.ratio(period=period, lang="en")
        return df if df is not None else pd.DataFrame()
