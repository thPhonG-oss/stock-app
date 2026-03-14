"""
scheduler.py

APScheduler BlockingScheduler — điểm khởi chạy chính của data pipeline.
Chuỗi khởi động:
  1. Setup logging
  2. Init database schema (schema.sql)
  3. Bootstrap listing sync (chạy đồng bộ 1 lần)
  4. Đăng ký tất cả cron jobs
  5. Start scheduler (blocking)
"""

import sys
import signal

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config import settings, setup_logging
from db.schema_init import init_schema

from jobs.listing_jobs import job_sync_listing
from jobs.market_jobs import job_fetch_ohlcv_daily
from jobs.company_jobs import job_fetch_company_profiles
from jobs.finance_jobs import job_fetch_financial_statements
from jobs.trading_jobs import job_fetch_foreign_flow


def create_scheduler() -> BlockingScheduler:
    """Tạo và cấu hình APScheduler."""
    scheduler = BlockingScheduler(
        timezone="Asia/Ho_Chi_Minh",
        job_defaults={
            "coalesce": True,            # Gộp nhiều lần miss thành 1 lần chạy
            "max_instances": 1,           # Chỉ cho phép 1 instance chạy cùng lúc
            "misfire_grace_time": 3600,   # Cho phép trễ tối đa 1 giờ
        },
    )

    # ── 1. Listing Sync — Thứ 2, 7:00 AM ────────────────────────────
    scheduler.add_job(
        job_sync_listing,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="refresh_symbol_listing",
        name="Đồng bộ danh sách mã CK + ICB",
        replace_existing=True,
    )

    # ── 2. OHLCV Daily — Thứ 2-6, 5:30 PM ──────────────────────────
    scheduler.add_job(
        job_fetch_ohlcv_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=30),
        id="fetch_ohlcv_daily_all",
        name="Lấy OHLCV daily tất cả symbols",
        replace_existing=True,
    )

    # ── 3. Company Profiles — Thứ 2, 8:00 AM ───────────────────────
    scheduler.add_job(
        job_fetch_company_profiles,
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="fetch_company_profile_all",
        name="Lấy thông tin công ty",
        replace_existing=True,
    )

    # ── 4. Financial Statements — Ngày 1 mỗi tháng, 9:00 AM ───────
    scheduler.add_job(
        job_fetch_financial_statements,
        trigger=CronTrigger(day=1, hour=9, minute=0),
        id="fetch_financial_statements_all",
        name="Lấy báo cáo tài chính",
        replace_existing=True,
    )

    # ── 5. Foreign Flow — Thứ 2-6, 5:45 PM ─────────────────────────
    scheduler.add_job(
        job_fetch_foreign_flow,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=45),
        id="fetch_foreign_flow_all",
        name="Lấy giao dịch khối ngoại",
        replace_existing=True,
    )

    return scheduler


def bootstrap():
    """
    Chạy các bước khởi tạo 1 lần khi pipeline start:
    1. Init schema nếu chưa init
    2. Đồng bộ listing (để các job khác có symbols để xử lý)
    """
    logger.info("═" * 60)
    logger.info("  STOCK DATA PIPELINE — BOOTSTRAP")
    logger.info("═" * 60)

    # 1. Init schema
    logger.info("[ BOOTSTRAP ] Initializing database schema...")
    try:
        init_schema()
        logger.success("[ BOOTSTRAP ] Schema initialized successfully")
    except Exception as e:
        logger.error("[ BOOTSTRAP ] Schema init failed: {}", e)
        raise

    # 2. Listing sync
    logger.info("[ BOOTSTRAP ] Running initial listing sync...")
    try:
        job_sync_listing()
        logger.success("[ BOOTSTRAP ] Listing sync completed")
    except Exception as e:
        logger.warning("[ BOOTSTRAP ] Listing sync failed: {} — continuing anyway", e)


def shutdown_handler(signum, frame):
    """Xử lý graceful shutdown."""
    logger.info("Nhận tín hiệu shutdown ({})... đang dừng scheduler", signum)
    sys.exit(0)


def main():
    """Entry point chính."""
    # Setup
    setup_logging()
    logger.info("Data Pipeline starting up...")
    logger.info("VNSTOCK_SOURCE: {}", settings.VNSTOCK_SOURCE)
    logger.info("Database: {}", settings.DB_HOST)

    # Graceful shutdown handlers
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Bootstrap
    bootstrap()

    # Start scheduler
    scheduler = create_scheduler()
    logger.info("═" * 60)
    logger.info("  SCHEDULER STARTED — {} jobs registered", len(scheduler.get_jobs()))
    logger.info("═" * 60)
    for job in scheduler.get_jobs():
        logger.info("  📋 {} → {}", job.id, getattr(job, "next_run_time", job.trigger))

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
