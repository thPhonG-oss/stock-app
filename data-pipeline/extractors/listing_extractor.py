"""
extractors/listing_extractor.py

Trích xuất dữ liệu listing (danh sách mã CK, ngành ICB) từ vnstock.
"""

import pandas as pd
from loguru import logger
from sources.vnstock_source import VnstockSource


class ListingExtractor:
    """Gọi vnstock Listing API để lấy master data."""

    @staticmethod
    def extract_all_symbols() -> pd.DataFrame:
        """
        Lấy toàn bộ danh sách mã chứng khoán.
        Returns: DataFrame với các cột: symbol, organ_name, en_organ_name,
                 organ_short_name, exchange, ...
        """
        logger.info("Extracting: tất cả symbols từ Listing.all_symbols()")
        client = VnstockSource.listing()
        df = client.all_symbols()
        logger.info("Extracted {} symbols", len(df))
        return df

    @staticmethod
    def extract_industries_icb() -> pd.DataFrame:
        """
        Lấy bảng phân ngành ICB.
        Returns: DataFrame với cột: icb_code, name_vn, name_en, level, parent_code
        """
        logger.info("Extracting: ngành ICB từ Listing.industries_icb()")
        client = VnstockSource.listing()
        df = client.industries_icb()
        logger.info("Extracted {} ICB records", len(df))
        return df
