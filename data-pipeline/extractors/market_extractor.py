"""
extractors/market_extractor.py

Trích xuất dữ liệu giá OHLCV từ vnstock Quote API.
"""

import pandas as pd
from loguru import logger
from sources.vnstock_source import VnstockSource


class MarketExtractor:
    """Gọi vnstock Quote API để lấy dữ liệu giá."""

    @staticmethod
    def extract_ohlcv_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
        """
        Lấy dữ liệu OHLCV daily cho 1 symbol.

        Args:
            symbol: Mã CK (VD: 'VNM')
            start: Ngày bắt đầu 'YYYY-MM-DD'
            end: Ngày kết thúc 'YYYY-MM-DD'

        Returns:
            DataFrame OHLCV raw từ vnstock
        """
        logger.debug("Extracting OHLCV daily: {} ({} → {})", symbol, start, end)
        client = VnstockSource.quote(symbol=symbol)
        df = client.history(
            symbol=symbol,
            start=start,
            end=end,
            interval="1D",
        )
        if df is not None and not df.empty:
            logger.debug("Extracted {} OHLCV rows for {}", len(df), symbol)
        else:
            logger.warning("Không có dữ liệu OHLCV cho {} ({} → {})", symbol, start, end)
            df = pd.DataFrame()
        return df
