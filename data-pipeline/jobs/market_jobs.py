"""
jobs/market_jobs.py

Job lấy dữ liệu OHLCV daily cho tất cả active symbols.
Hỗ trợ incremental: chỉ fetch từ ngày cuối cùng đã có trong DB.
"""

import time
from datetime import date, timedelta, datetime

from loguru import logger
from config.settings import settings
from extractors.market_extractor import MarketExtractor
from transformers.market_transformer import MarketTransformer
from loaders.market_loader import MarketLoader
from loaders.base_loader import BaseLoader
from db.repositories.listing_repo import ListingRepository


def job_fetch_ohlcv_daily():
    """
    Job: Lấy OHLCV daily cho tất cả active symbols.

    Logic incremental:
    - Kiểm tra ngày mới nhất đã có trong DB → chỉ fetch từ ngày đó + 1
    - Nếu chưa có data → fetch từ lookback_years (mặc định 3 năm)

    Lịch chạy: mỗi ngày 17:30 (sau khi thị trường đóng cửa)
    """
    logger.info("═" * 60)
    logger.info("▶ Bắt đầu job: Fetch OHLCV Daily")
    logger.info("═" * 60)

    today = date.today()
    lookback_start = today - timedelta(days=settings.BOOTSTRAP_LOOKBACK_DAYS)
    batch_size = settings.BATCH_SIZE

    # Lấy danh sách symbols
    with BaseLoader.connect() as conn:
        repo = ListingRepository(conn)
        symbols = repo.get_all_symbols()

    if not symbols:
        logger.warning("Không có symbols nào trong DB. Chạy listing sync trước!")
        return

    logger.info("Chuẩn bị fetch OHLCV cho {} symbols", len(symbols))

    total_rows = 0
    errors = 0

    # Xử lý theo batch để tránh quá tải
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i: i + batch_size]
        logger.info("Processing batch {}/{} ({} symbols)", i // batch_size + 1,
                     (len(symbols) + batch_size - 1) // batch_size, len(batch))

        for sym_row in batch:
            symbol = sym_row["symbol"] if isinstance(sym_row, dict) else sym_row
            exchange = sym_row.get("exchange", "UNKNOWN") if isinstance(sym_row, dict) else "UNKNOWN"

            try:
                # Kiểm tra ngày cuối cùng đã có
                latest = MarketLoader.get_latest_date(symbol, "1D")
                if latest:
                    # Start from the day AFTER the last known date to avoid re-fetching
                    start_date = str(datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1))
                else:
                    start_date = str(lookback_start)

                end_date = str(today)

                # Extract
                df = MarketExtractor.extract_ohlcv_daily(symbol, start_date, end_date)
                if df is None or df.empty:
                    continue

                # Transform
                records = MarketTransformer.transform_ohlcv_daily(df, symbol, exchange)
                if not records:
                    continue

                # Load
                loaded = MarketLoader.load_ohlcv_daily(records)
                total_rows += loaded

            except Exception as e:
                logger.warning("Lỗi OHLCV cho {}: {}", symbol, e)
                errors += 1
                continue

            # Rate limiting — tránh bị block API
            time.sleep(0.3)

    logger.success(
        "✓ OHLCV Daily hoàn tất — {} rows loaded, {} errors",
        total_rows, errors,
    )
