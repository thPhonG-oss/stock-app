"""
extractors/company_extractor.py

Trích xuất dữ liệu công ty (profile, shareholders, officers, events) từ vnstock.
"""

import pandas as pd
from loguru import logger
from sources.vnstock_source import VnstockSource


class CompanyExtractor:
    """Gọi vnstock Company API để lấy thông tin doanh nghiệp."""

    @staticmethod
    def extract_overview(symbol: str) -> pd.DataFrame:
        """Lấy thông tin tổng quan công ty."""
        logger.debug("Extracting company overview: {}", symbol)
        client = VnstockSource.company(symbol)
        df = client.overview()
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def extract_shareholders(symbol: str) -> pd.DataFrame:
        """Lấy danh sách cổ đông."""
        logger.debug("Extracting shareholders: {}", symbol)
        client = VnstockSource.company(symbol)
        df = client.shareholders()
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def extract_officers(symbol: str) -> pd.DataFrame:
        """Lấy danh sách ban lãnh đạo."""
        logger.debug("Extracting officers: {}", symbol)
        client = VnstockSource.company(symbol)
        df = client.officers()
        return df if df is not None else pd.DataFrame()

    @staticmethod
    def extract_events(symbol: str) -> pd.DataFrame:
        """Lấy danh sách sự kiện công ty."""
        logger.debug("Extracting events: {}", symbol)
        client = VnstockSource.company(symbol)
        df = client.events()
        return df if df is not None else pd.DataFrame()
