"""
transformers/trading_transformer.py

Chuyển đổi DataFrame giao dịch từ vnstock → list[dict] cho trading.* tables.
"""

import pandas as pd
from loguru import logger
from config.settings import settings


class TradingTransformer:
    """Chuyển đổi dữ liệu trading từ DataFrame sang records cho DB."""

    @classmethod
    def transform_foreign_flow(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """
        Chuyển Trading.foreign_trade() → records cho TradingRepository.upsert_foreign_flow().

        vnstock Trading.foreign_trade() trả về các cột dạng:
          trade_date, buy_volume, buy_value, sell_volume, sell_value,
          net_volume, net_value, room_remaining (tuỳ source)
        """
        if df is None or df.empty:
            return []

        source = settings.VNSTOCK_SOURCE
        records = []

        for _, row in df.iterrows():
            trade_date = row.get("trade_date", row.get("trading_date", row.get("date")))
            if trade_date is None:
                continue

            try:
                trade_date = pd.Timestamp(trade_date).date()
            except Exception:
                continue

            records.append({
                "symbol": symbol.upper(),
                "trade_date": trade_date,
                "buy_volume": _safe_int(row.get("buy_volume", row.get("buy_foreign_quantity"))),
                "buy_value": _safe_num(row.get("buy_value", row.get("buy_foreign_value"))),
                "sell_volume": _safe_int(row.get("sell_volume", row.get("sell_foreign_quantity"))),
                "sell_value": _safe_num(row.get("sell_value", row.get("sell_foreign_value"))),
                "net_volume": _safe_int(row.get("net_volume", row.get("net_foreign_quantity"))),
                "net_value": _safe_num(row.get("net_value", row.get("net_foreign_value"))),
                "room_remaining": _safe_int(row.get("room_remaining", row.get("current_room"))),
                "data_source": source,
            })

        logger.debug("Transformed {} foreign flow records for {}", len(records), symbol)
        return records


def _safe_num(val):
    if val is None:
        return None
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None:
        return None
    try:
        f = float(val)
        return int(f) if pd.notna(f) else None
    except (ValueError, TypeError):
        return None
