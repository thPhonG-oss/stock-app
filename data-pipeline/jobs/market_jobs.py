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


def job_fetch_ohlcv_daily(
    start_date: str | None = None,
    end_date: str | None = None,
    symbols_filter: list[str] | None = None,
):
    """
    Job: Lấy OHLCV daily cho tất cả active symbols.

    Logic incremental:
    - Kiểm tra ngày mới nhất đã có trong DB → chỉ fetch từ ngày đó + 1
    - Nếu chưa có data → fetch từ lookback_years (mặc định 3 năm)

    Args:
        start_date: Override ngày bắt đầu (YYYY-MM-DD). Nếu None → dùng incremental logic.
        end_date: Override ngày kết thúc (YYYY-MM-DD). Nếu None → today.
        symbols_filter: Chỉ chạy cho các symbols này. Nếu None → tất cả.

    Lịch chạy: mỗi ngày 17:30 (sau khi thị trường đóng cửa)
    """
    logger.info("═" * 60)
    logger.info("▶ Bắt đầu job: Fetch OHLCV Daily")
    logger.info("═" * 60)

    today = date.today()
    lookback_start = today - timedelta(days=settings.BOOTSTRAP_LOOKBACK_DAYS)
    batch_size = settings.BATCH_SIZE
    forced_end = end_date or str(today)

    # Lấy danh sách symbols
    with BaseLoader.connect() as conn:
        repo = ListingRepository(conn)
        symbols = repo.get_all_symbols()

    if symbols_filter:
        symbols_filter_upper = [s.upper() for s in symbols_filter]
        symbols = [s for s in symbols if
                   (s["symbol"] if isinstance(s, dict) else s).upper() in symbols_filter_upper]
        logger.info("Filtered to {} symbols: {}", len(symbols), symbols_filter_upper)

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
                if start_date:
                    fetch_start = start_date
                else:
                    latest = MarketLoader.get_latest_date(symbol, "1D")
                    if latest:
                        fetch_start = str(datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1))
                    else:
                        fetch_start = str(lookback_start)

                fetch_end = forced_end

                # Extract
                df = MarketExtractor.extract_ohlcv_daily(symbol, fetch_start, fetch_end)
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
