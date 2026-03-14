"""
loaders/base_loader.py

Base class cho tất cả loader.
Cung cấp context manager cho DB connection + ETL job tracking.
"""

import traceback
from contextlib import contextmanager

from loguru import logger
from db.engine import get_engine
from db.repositories.etl_repo import EtlRepository


class BaseLoader:
    """
    Base loader cung cấp:
    - Connection management qua context manager
    - ETL job run tracking (start/finish)
    """

    @staticmethod
    @contextmanager
    def connect():
        """
        Context manager mở connection từ pool, tự động đóng khi xong.

        Usage:
            with BaseLoader.connect() as conn:
                repo = SomeRepository(conn)
                repo.upsert(...)
        """
        engine = get_engine()
        conn = engine.connect()
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    @contextmanager
    def tracked_job(conn, job_id: str, **kwargs):
        """
        Context manager ghi nhận ETL job run vào etl.job_run.

        Usage:
            with BaseLoader.connect() as conn:
                with BaseLoader.tracked_job(conn, 'fetch_ohlcv_daily_all') as tracker:
                    # ... do work ...
                    tracker['rows_inserted'] = 100

        Args:
            conn: SQLAlchemy connection
            job_id: ID của job (phải tồn tại trong etl.job_definition)
            **kwargs: symbol, target_tier, target_interval, date_from, date_to
        """
        etl = EtlRepository(conn)
        tracker = {
            "rows_fetched": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_skipped": 0,
        }

        try:
            run_id = etl.start_job_run(job_id, **kwargs)
            logger.info("▶ Job '{}' started (run_id={})", job_id, run_id)
        except Exception:
            # Nếu job_id chưa tồn tại trong etl.job_definition, bỏ qua tracking
            logger.warning("Không thể track job '{}' — chưa có trong etl.job_definition", job_id)
            yield tracker
            return

        try:
            yield tracker
            etl.finish_job_run(
                run_id,
                status="success",
                rows_fetched=tracker["rows_fetched"],
                rows_inserted=tracker["rows_inserted"],
                rows_updated=tracker["rows_updated"],
                rows_skipped=tracker["rows_skipped"],
            )
            logger.success(
                "✓ Job '{}' completed — fetched={}, inserted={}, updated={}, skipped={}",
                job_id,
                tracker["rows_fetched"],
                tracker["rows_inserted"],
                tracker["rows_updated"],
                tracker["rows_skipped"],
            )
        except Exception as exc:
            tb = traceback.format_exc()
            etl.finish_job_run(
                run_id,
                status="failed",
                rows_fetched=tracker["rows_fetched"],
                rows_inserted=tracker["rows_inserted"],
                error_message=str(exc)[:500],
                error_traceback=tb[:2000],
            )
            logger.error("✗ Job '{}' failed: {}", job_id, exc)
            raise
