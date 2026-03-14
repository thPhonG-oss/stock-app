from sqlalchemy import text

from db.repositories.base import BaseRepository


class TradingRepository(BaseRepository):
    def upsert_foreign_flow(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO trading.foreign_flow
                    (symbol, trade_date, buy_volume, buy_value,
                     sell_volume, sell_value, net_volume, net_value,
                     room_remaining, data_source, fetched_at)
                VALUES
                    (:symbol, :trade_date, :buy_volume, :buy_value,
                     :sell_volume, :sell_value, :net_volume, :net_value,
                     :room_remaining, :data_source, NOW())
                ON CONFLICT (symbol, trade_date, data_source) DO UPDATE SET
                    buy_volume     = EXCLUDED.buy_volume,
                    buy_value      = EXCLUDED.buy_value,
                    sell_volume    = EXCLUDED.sell_volume,
                    sell_value     = EXCLUDED.sell_value,
                    net_volume     = EXCLUDED.net_volume,
                    net_value      = EXCLUDED.net_value,
                    room_remaining = EXCLUDED.room_remaining,
                    fetched_at     = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def upsert_trading_stats(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO trading.trading_stat
                    (symbol, trade_date, total_volume, total_value,
                     avg_price, total_trades, buy_volume, sell_volume,
                     data_source, fetched_at)
                VALUES
                    (:symbol, :trade_date, :total_volume, :total_value,
                     :avg_price, :total_trades, :buy_volume, :sell_volume,
                     :data_source, NOW())
                ON CONFLICT (symbol, trade_date, data_source) DO UPDATE SET
                    total_volume  = EXCLUDED.total_volume,
                    total_value   = EXCLUDED.total_value,
                    avg_price     = EXCLUDED.avg_price,
                    total_trades  = EXCLUDED.total_trades,
                    buy_volume    = EXCLUDED.buy_volume,
                    sell_volume   = EXCLUDED.sell_volume,
                    fetched_at    = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)
