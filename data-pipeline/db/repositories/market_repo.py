from sqlalchemy import text

from db.repositories.base import BaseRepository


class MarketRepository(BaseRepository):
    # ── OHLCV daily ────────────────────────────────────────────────────────

    def upsert_ohlcv_daily(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO market.ohlcv_daily
                    (symbol, interval, traded_at, exchange,
                     open, high, low, close, volume, value,
                     reference_price, ceiling_price, floor_price,
                     foreign_buy_vol, foreign_sell_vol, foreign_net_vol,
                     put_through_vol, put_through_val, total_trades,
                     data_source)
                VALUES
                    (:symbol, :interval, :traded_at, :exchange,
                     :open, :high, :low, :close, :volume, :value,
                     :reference_price, :ceiling_price, :floor_price,
                     :foreign_buy_vol, :foreign_sell_vol, :foreign_net_vol,
                     :put_through_vol, :put_through_val, :total_trades,
                     :data_source)
                ON CONFLICT (symbol, interval, traded_at) DO NOTHING
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def get_latest_ohlcv_date(self, symbol: str, interval: str) -> str | None:
        row = self.conn.execute(
            text(
                """
                SELECT MAX(traded_at)::DATE
                FROM market.ohlcv_daily
                WHERE symbol = :symbol AND interval = :interval
                """
            ),
            {"symbol": symbol, "interval": interval},
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    # ── OHLCV intraday ─────────────────────────────────────────────────────

    def upsert_ohlcv_intraday(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO market.ohlcv_intraday
                    (symbol, interval, traded_at, exchange,
                     open, high, low, close, volume, value,
                     data_source)
                VALUES
                    (:symbol, :interval, :traded_at, :exchange,
                     :open, :high, :low, :close, :volume, :value,
                     :data_source)
                ON CONFLICT (symbol, interval, traded_at) DO NOTHING
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    # ── Intraday trades ────────────────────────────────────────────────────

    def upsert_intraday_trades(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO market.intraday_trade
                    (symbol, traded_at, price, volume, match_type, trade_id,
                     price_change, accum_volume, accum_value, exchange, data_source)
                VALUES
                    (:symbol, :traded_at, :price, :volume, :match_type, :trade_id,
                     :price_change, :accum_volume, :accum_value, :exchange, :data_source)
                ON CONFLICT (symbol, traded_at, trade_id) DO NOTHING
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    # ── Index OHLCV ────────────────────────────────────────────────────────

    def upsert_index_ohlcv(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO market.index_ohlcv
                    (index_code, interval, traded_at,
                     open, high, low, close, volume, value,
                     advances, declines, unchanged, data_source)
                VALUES
                    (:index_code, :interval, :traded_at,
                     :open, :high, :low, :close, :volume, :value,
                     :advances, :declines, :unchanged, :data_source)
                ON CONFLICT (index_code, interval, traded_at) DO NOTHING
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    # ── Market breadth ─────────────────────────────────────────────────────

    def upsert_market_breadth(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO market.market_breadth
                    (trade_date, exchange, advances, declines, unchanged, total_trading,
                     total_volume, total_value, new_highs_52w, new_lows_52w,
                     foreign_net_vol, foreign_net_val, data_source)
                VALUES
                    (:trade_date, :exchange, :advances, :declines, :unchanged, :total_trading,
                     :total_volume, :total_value, :new_highs_52w, :new_lows_52w,
                     :foreign_net_vol, :foreign_net_val, :data_source)
                ON CONFLICT (trade_date, exchange) DO UPDATE SET
                    advances       = EXCLUDED.advances,
                    declines       = EXCLUDED.declines,
                    unchanged      = EXCLUDED.unchanged,
                    total_trading  = EXCLUDED.total_trading,
                    total_volume   = EXCLUDED.total_volume,
                    total_value    = EXCLUDED.total_value,
                    new_highs_52w  = EXCLUDED.new_highs_52w,
                    new_lows_52w   = EXCLUDED.new_lows_52w,
                    foreign_net_vol = EXCLUDED.foreign_net_vol,
                    foreign_net_val = EXCLUDED.foreign_net_val
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)
