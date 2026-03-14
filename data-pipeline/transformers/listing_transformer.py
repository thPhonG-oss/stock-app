"""
transformers/listing_transformer.py

Chuyển đổi DataFrame từ vnstock Listing API → list[dict] cho DB schema.
Mapping columns từ vnstock output → listing.symbol, listing.icb_industry.
"""

import pandas as pd
from loguru import logger
from config.settings import settings


class ListingTransformer:
    """Chuyển đổi dữ liệu listing từ DataFrame sang records cho DB."""

    # ── Mapping tên cột vnstock → schema listing.symbol ───────────────
    # vnstock Listing.all_symbols() trả về các cột dạng:
    #   ticker (hoặc symbol), organ_name, en_organ_name, organ_short_name,
    #   exchange (HOSE/HNX/UPCOM), icb_code, listing_date, ...

    EXCHANGE_MAP = {
        "HOSE": "HOSE",
        "HSX": "HOSE",
        "HNX": "HNX",
        "UPCOM": "UPCOM",
    }

    ASSET_TYPE_MAP = {
        "STOCK": "stock",
        "ETF": "etf",
        "CW": "cw",
        "BOND": "bond",
    }

    @classmethod
    def transform_symbols(cls, df: pd.DataFrame) -> list[dict]:
        """
        Chuyển DataFrame all_symbols → records cho ListingRepository.upsert_symbols().
        """
        if df is None or df.empty:
            return []

        records = []
        source = settings.VNSTOCK_SOURCE

        for _, row in df.iterrows():
            # Xác định tên cột — vnstock có thể dùng 'ticker' hoặc 'symbol'
            symbol = str(row.get("ticker", row.get("symbol", ""))).strip().upper()
            if not symbol:
                continue

            exchange_raw = str(row.get("exchange", row.get("organ_type_code", "UNKNOWN"))).upper()
            exchange = cls.EXCHANGE_MAP.get(exchange_raw, "UNKNOWN")

            asset_type_raw = str(row.get("type", row.get("asset_type", "stock"))).upper()
            asset_type = cls.ASSET_TYPE_MAP.get(asset_type_raw, "stock")

            records.append({
                "symbol": symbol,
                "company_name": row.get("organ_name", row.get("company_name", None)),
                "company_name_en": row.get("en_organ_name", row.get("company_name_en", None)),
                "exchange": exchange,
                "asset_type": asset_type,
                "icb_code": row.get("icb_code", row.get("icb_code3", None)),
                "is_active": True,
                "listing_date": _parse_date(row.get("listing_date")),
                "delisting_date": _parse_date(row.get("delisting_date")),
                "data_source": source,
            })

        logger.info("Transformed {} symbol records", len(records))
        return records

    @classmethod
    def transform_industries_icb(cls, df: pd.DataFrame) -> list[dict]:
        """
        Chuyển DataFrame industries_icb → records cho ListingRepository.upsert_icb_industries().
        """
        if df is None or df.empty:
            return []

        records = []
        source = settings.VNSTOCK_SOURCE

        for _, row in df.iterrows():
            icb_code = str(row.get("icb_code", row.get("icb_code", ""))).strip()
            if not icb_code:
                continue

            records.append({
                "icb_code": icb_code,
                "name_vn": row.get("icb_name", row.get("name_vn", None)),
                "name_en": row.get("en_icb_name", row.get("name_en", None)),
                "level": int(row.get("level", row.get("icb_level", 1))),
                "parent_code": row.get("parent_code", None),
                "data_source": source,
            })

        logger.info("Transformed {} ICB records", len(records))
        return records


def _parse_date(val):
    """An toàn parse date, trả về None nếu không hợp lệ."""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None
