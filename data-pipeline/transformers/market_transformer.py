"""
transformers/market_transformer.py

Chuyển đổi DataFrame OHLCV từ vnstock → list[dict] cho market.ohlcv_daily.
"""

import pandas as pd
from loguru import logger
from config.settings import settings


class MarketTransformer:
    """Chuyển đổi dữ liệu OHLCV từ DataFrame sang records cho DB."""

    @classmethod
    def transform_ohlcv_daily(
        cls, df: pd.DataFrame, symbol: str, exchange: str = "UNKNOWN"
    ) -> list[dict]:
        """
        Chuyển OHLCV DataFrame → records cho MarketRepository.upsert_ohlcv_daily().

        vnstock Quote.history() trả về các cột:
            time, open, high, low, close, volume,
            (tuỳ source: value, foreign_buy, foreign_sell, ...)
        """
        if df is None or df.empty:
            return []

        records = []
        source = settings.VNSTOCK_SOURCE
        symbol = symbol.upper()

        for _, row in df.iterrows():
            # Xác định timestamp
            traded_at = row.get("time", row.get("date", row.get("trading_date", None)))
            if traded_at is None:
                continue

            try:
                traded_at = pd.Timestamp(traded_at)
            except Exception:
                continue

            records.append({
                "symbol": symbol,
                "interval": "1D",
                "traded_at": traded_at,
                "exchange": exchange,
                "open": _safe_float(row.get("open")),
                "high": _safe_float(row.get("high")),
                "low": _safe_float(row.get("low")),
                "close": _safe_float(row.get("close")),
                "volume": _safe_int(row.get("volume", 0)),
                "value": _safe_float(row.get("value")),
                "reference_price": _safe_float(row.get("reference_price", row.get("ref_price"))),
                "ceiling_price": _safe_float(row.get("ceiling_price", row.get("ceiling"))),
                "floor_price": _safe_float(row.get("floor_price", row.get("floor"))),
                "foreign_buy_vol": _safe_int(row.get("foreign_buy_volume", row.get("buy_foreign_quantity"))),
                "foreign_sell_vol": _safe_int(row.get("foreign_sell_volume", row.get("sell_foreign_quantity"))),
                "foreign_net_vol": _safe_int(row.get("foreign_net_vol")),
                "put_through_vol": _safe_int(row.get("put_through_vol")),
                "put_through_val": _safe_float(row.get("put_through_val")),
                "total_trades": _safe_int(row.get("total_trades")),
                "data_source": source,
            })

        logger.debug("Transformed {} OHLCV daily records for {}", len(records), symbol)
        return records


def _safe_float(val):
    """An toàn chuyển sang float, trả về None nếu lỗi."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    """An toàn chuyển sang int, trả về None nếu lỗi."""
    if val is None:
        return None
    try:
        f = float(val)
        return int(f) if pd.notna(f) else None
    except (ValueError, TypeError):
        return None
