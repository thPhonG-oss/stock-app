"""
extractors/trading_extractor.py

Trích xuất dữ liệu giao dịch (foreign flow, trading stats) từ vnstock.
"""

import pandas as pd
from loguru import logger
from sources.vnstock_source import VnstockSource


class TradingExtractor:
    """Gọi vnstock Trading API để lấy dữ liệu giao dịch."""

    @staticmethod
    def extract_foreign_trade(symbol: str, start: str, end: str) -> pd.DataFrame:
        """
        Lấy dữ liệu giao dịch khối ngoại.

        Args:
            symbol: Mã CK
            start: Ngày bắt đầu 'YYYY-MM-DD'
            end: Ngày kết thúc 'YYYY-MM-DD'
        """
        logger.debug("Extracting foreign trade: {} ({} → {})", symbol, start, end)
        client = VnstockSource.trading(symbol)
        try:
            df = client.foreign_trade(start=start, end=end)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.warning("Không lấy được foreign trade cho {}: {}", symbol, e)
            return pd.DataFrame()
