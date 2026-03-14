import socket
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from db.repositories.base import BaseRepository


class EtlRepository(BaseRepository):
    # ── Job run ────────────────────────────────────────────────────────────

    def start_job_run(
        self,
        job_id: str,
        symbol: str | None = None,
        target_tier: int | None = None,
        target_interval: str | None = None,
        date_from=None,
        date_to=None,
    ) -> int:
        row = self.conn.execute(
            text(
                """
                INSERT INTO etl.job_run
                    (job_id, run_at, status, symbol, target_tier,
                     target_interval, date_from, date_to, host_name, pid)
                VALUES
                    (:job_id, NOW(), 'running', :symbol, :target_tier,
                     :target_interval, :date_from, :date_to, :host_name, :pid)
                RETURNING id
                """
            ),
            {
                "job_id": job_id,
                "symbol": symbol,
                "target_tier": target_tier,
                "target_interval": target_interval,
                "date_from": date_from,
                "date_to": date_to,
                "host_name": socket.gethostname(),
                "pid": os.getpid(),
            },
        ).fetchone()
        self.conn.commit()
        return row[0]

    def finish_job_run(
        self,
        run_id: int,
        status: str,
        rows_fetched: int = 0,
        rows_inserted: int = 0,
        rows_updated: int = 0,
        rows_skipped: int = 0,
        error_message: str | None = None,
        error_traceback: str | None = None,
    ) -> None:
        self.conn.execute(
            text(
                """
                UPDATE etl.job_run SET
                    finished_at     = NOW(),
                    duration_ms     = EXTRACT(EPOCH FROM (NOW() - run_at))::INT * 1000,
                    status          = :status,
                    rows_fetched    = :rows_fetched,
                    rows_inserted   = :rows_inserted,
                    rows_updated    = :rows_updated,
                    rows_skipped    = :rows_skipped,
                    error_message   = :error_message,
                    error_traceback = :error_traceback
                WHERE id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "rows_fetched": rows_fetched,
                "rows_inserted": rows_inserted,
                "rows_updated": rows_updated,
                "rows_skipped": rows_skipped,
                "error_message": error_message,
                "error_traceback": error_traceback,
            },
        )
        self.conn.commit()

    # ── Data freshness ─────────────────────────────────────────────────────

    def get_freshness(
        self, symbol: str, data_type: str, data_source: str
    ) -> dict | None:
        row = self.conn.execute(
            text(
                """
                SELECT symbol, data_type, data_source, earliest_date, latest_date,
                       row_count, is_bootstrapped, bootstrap_started_at,
                       bootstrap_completed_at, last_successful_fetch,
                       consecutive_failures
                FROM etl.data_freshness
                WHERE symbol = :symbol AND data_type = :data_type
                  AND data_source = :data_source
                """
            ),
            {"symbol": symbol, "data_type": data_type, "data_source": data_source},
        ).fetchone()
        return dict(row._mapping) if row else None

    def upsert_freshness(
        self,
        symbol: str,
        data_type: str,
        target_table: str,
        data_source: str,
        earliest_date=None,
        latest_date=None,
        row_count: int = 0,
        is_bootstrapped: bool = False,
        bootstrap_started_at=None,
        bootstrap_completed_at=None,
        success: bool = True,
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO etl.data_freshness
                    (symbol, data_type, target_table, data_source,
                     earliest_date, latest_date, row_count,
                     is_bootstrapped, bootstrap_started_at, bootstrap_completed_at,
                     last_successful_fetch, last_attempted_fetch,
                     consecutive_failures, updated_at)
                VALUES
                    (:symbol, :data_type, :target_table, :data_source,
                     :earliest_date, :latest_date, :row_count,
                     :is_bootstrapped, :bootstrap_started_at, :bootstrap_completed_at,
                     CASE WHEN :success THEN NOW() ELSE NULL END,
                     NOW(),
                     CASE WHEN :success THEN 0 ELSE 1 END,
                     NOW())
                ON CONFLICT (symbol, data_type, data_source) DO UPDATE SET
                    target_table            = EXCLUDED.target_table,
                    earliest_date           = COALESCE(EXCLUDED.earliest_date,
                                                       etl.data_freshness.earliest_date),
                    latest_date             = COALESCE(EXCLUDED.latest_date,
                                                       etl.data_freshness.latest_date),
                    row_count               = EXCLUDED.row_count,
                    is_bootstrapped         = EXCLUDED.is_bootstrapped,
                    bootstrap_started_at    = COALESCE(EXCLUDED.bootstrap_started_at,
                                                       etl.data_freshness.bootstrap_started_at),
                    bootstrap_completed_at  = COALESCE(EXCLUDED.bootstrap_completed_at,
                                                       etl.data_freshness.bootstrap_completed_at),
                    last_successful_fetch   = CASE WHEN :success THEN NOW()
                                             ELSE etl.data_freshness.last_successful_fetch END,
                    last_attempted_fetch    = NOW(),
                    consecutive_failures    = CASE WHEN :success THEN 0
                                             ELSE etl.data_freshness.consecutive_failures + 1 END,
                    updated_at              = NOW()
                """
            ),
            {
                "symbol": symbol,
                "data_type": data_type,
                "target_table": target_table,
                "data_source": data_source,
                "earliest_date": earliest_date,
                "latest_date": latest_date,
                "row_count": row_count,
                "is_bootstrapped": is_bootstrapped,
                "bootstrap_started_at": bootstrap_started_at,
                "bootstrap_completed_at": bootstrap_completed_at,
                "success": success,
            },
        )
        self.conn.commit()

    def is_bootstrapped(self, symbol: str, data_type: str, data_source: str) -> bool:
        row = self.conn.execute(
            text(
                """
                SELECT is_bootstrapped FROM etl.data_freshness
                WHERE symbol = :symbol AND data_type = :data_type
                  AND data_source = :data_source
                """
            ),
            {"symbol": symbol, "data_type": data_type, "data_source": data_source},
        ).fetchone()
        return bool(row[0]) if row else False

    # ── Symbol collection config ───────────────────────────────────────────

    def get_symbols_for_tier(self, tier: int) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT scc.symbol, scc.tier, scc.priority,
                       scc.override_ohlcv_daily, scc.override_ohlcv_intraday,
                       scc.override_ticks, scc.override_company,
                       scc.override_finance, scc.override_trading_flow,
                       ct.collect_ohlcv_daily, ct.collect_ohlcv_intraday,
                       ct.intraday_intervals, ct.collect_ticks,
                       ct.collect_company, ct.collect_finance,
                       ct.collect_trading_flow, ct.bootstrap_days
                FROM etl.symbol_collection_config scc
                JOIN etl.collection_tier ct ON ct.tier = scc.tier
                WHERE scc.tier = :tier AND scc.is_active = TRUE
                ORDER BY scc.priority, scc.symbol
                """
            ),
            {"tier": tier},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_all_active_symbols(self) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT scc.symbol, scc.tier, scc.priority,
                       ct.collect_ohlcv_daily, ct.collect_ohlcv_intraday,
                       ct.intraday_intervals, ct.collect_ticks,
                       ct.collect_company, ct.collect_finance,
                       ct.collect_trading_flow, ct.bootstrap_days
                FROM etl.symbol_collection_config scc
                JOIN etl.collection_tier ct ON ct.tier = scc.tier
                WHERE scc.is_active = TRUE
                ORDER BY scc.priority, scc.tier, scc.symbol
                """
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    def upsert_symbol_collection(
        self, symbol: str, tier: int, priority: int = 5
    ) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO etl.symbol_collection_config (symbol, tier, priority)
                VALUES (:symbol, :tier, :priority)
                ON CONFLICT (symbol) DO UPDATE SET
                    tier       = EXCLUDED.tier,
                    priority   = EXCLUDED.priority,
                    is_active  = TRUE
                """
            ),
            {"symbol": symbol, "tier": tier, "priority": priority},
        )
        self.conn.commit()

    # ── Pipeline state ─────────────────────────────────────────────────────

    def get_state(self, key: str) -> Any | None:
        row = self.conn.execute(
            text(
                "SELECT value_text, value_int, value_bool, value_ts "
                "FROM etl.pipeline_state WHERE key = :key"
            ),
            {"key": key},
        ).fetchone()
        if row is None:
            return None
        m = row._mapping
        return m["value_bool"] if m["value_bool"] is not None else (
            m["value_ts"] if m["value_ts"] is not None else (
                m["value_int"] if m["value_int"] is not None else m["value_text"]
            )
        )

    def set_state(self, key: str, **kwargs) -> None:
        """Set a pipeline_state flag. Accepts value_text, value_int, value_bool, value_ts."""
        self.conn.execute(
            text(
                """
                INSERT INTO etl.pipeline_state (key, value_text, value_int, value_bool, value_ts, updated_at)
                VALUES (:key, :value_text, :value_int, :value_bool, :value_ts, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value_text = EXCLUDED.value_text,
                    value_int  = EXCLUDED.value_int,
                    value_bool = EXCLUDED.value_bool,
                    value_ts   = EXCLUDED.value_ts,
                    updated_at = NOW()
                """
            ),
            {
                "key": key,
                "value_text": kwargs.get("value_text"),
                "value_int": kwargs.get("value_int"),
                "value_bool": kwargs.get("value_bool"),
                "value_ts": kwargs.get("value_ts"),
            },
        )
        self.conn.commit()
