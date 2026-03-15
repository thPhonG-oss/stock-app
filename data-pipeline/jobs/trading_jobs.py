"""
jobs/trading_jobs.py

Job lấy dữ liệu giao dịch khối ngoại.
"""

import time
from datetime import date, timedelta

from loguru import logger
from config.settings import settings
from extractors.trading_extractor import TradingExtractor
from transformers.trading_transformer import TradingTransformer
from loaders.trading_loader import TradingLoader
from loaders.base_loader import BaseLoader
from db.repositories.listing_repo import ListingRepository


def job_fetch_foreign_flow(
    start_date: str | None = None,
    end_date: str | None = None,
    symbols_filter: list[str] | None = None,
):
    """
    Job: Lấy foreign flow data cho tất cả active symbols.

    Args:
        start_date: Override ngày bắt đầu (YYYY-MM-DD). Nếu None → 30 ngày trước.
        end_date: Override ngày kết thúc (YYYY-MM-DD). Nếu None → today.
        symbols_filter: Chỉ chạy cho các symbols này. Nếu None → tất cả.

    Lịch chạy: mỗi ngày 17:45 (sau khi thị trường đóng cửa)
    """
    logger.info("═" * 60)
    logger.info("▶ Bắt đầu job: Fetch Foreign Flow")
    logger.info("═" * 60)

    today = date.today()
    fetch_start = start_date or str(today - timedelta(days=30))
    fetch_end = end_date or str(today)

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
        logger.warning("Không có symbols nào. Chạy listing sync trước!")
        return

    batch_size = settings.BATCH_SIZE
    total_rows = 0
    errors = 0

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i: i + batch_size]
        logger.info("Processing batch {}/{}", i // batch_size + 1,
                     (len(symbols) + batch_size - 1) // batch_size)

        for sym_row in batch:
            symbol = sym_row["symbol"] if isinstance(sym_row, dict) else sym_row

            try:
                # Extract
                df = TradingExtractor.extract_foreign_trade(symbol, fetch_start, fetch_end)
                if df is None or df.empty:
                    continue

                # Transform
                records = TradingTransformer.transform_foreign_flow(df, symbol)
                if not records:
                    continue

                # Load
                loaded = TradingLoader.load_foreign_flow(records)
                total_rows += loaded

            except Exception as e:
                logger.warning("Lỗi foreign flow cho {}: {}", symbol, e)
                errors += 1
                continue

            time.sleep(0.3)

    logger.success(
        "✓ Foreign Flow hoàn tất — {} rows loaded, {} errors",
        total_rows, errors,
    )
