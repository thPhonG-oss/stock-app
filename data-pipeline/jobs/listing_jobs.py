"""
jobs/listing_jobs.py

Job đồng bộ danh sách mã CK + ICB industries từ vnstock → PostgreSQL.
Đây là job chạy đầu tiên (bootstrap) và sau đó chạy hàng tuần.
"""

from loguru import logger
from extractors.listing_extractor import ListingExtractor
from transformers.listing_transformer import ListingTransformer
from loaders.listing_loader import ListingLoader


def job_sync_listing():
    """
    Job: Đồng bộ listing.symbol + listing.icb_industry.

    Pipeline: Extract (vnstock) → Transform (normalize) → Load (upsert DB)
    Lịch chạy: mỗi tuần Thứ 2 lúc 7:00 AM, và khi bootstrap.
    """
    logger.info("═" * 60)
    logger.info("▶ Bắt đầu job: Đồng bộ Listing")
    logger.info("═" * 60)

    total_symbols = 0
    total_icb = 0

    try:
        # ── 1. Đồng bộ Symbols ──────────────────────────────────
        logger.info("[ 1/2 ] Extracting all symbols...")
        df_symbols = ListingExtractor.extract_all_symbols()

        logger.info("[ 1/2 ] Transforming symbols...")
        symbol_records = ListingTransformer.transform_symbols(df_symbols)

        logger.info("[ 1/2 ] Loading {} symbols...", len(symbol_records))
        total_symbols = ListingLoader.load_symbols(symbol_records)

        # ── 2. Đồng bộ ICB Industries ───────────────────────────
        logger.info("[ 2/2 ] Extracting ICB industries...")
        df_icb = ListingExtractor.extract_industries_icb()

        logger.info("[ 2/2 ] Transforming ICB...")
        icb_records = ListingTransformer.transform_industries_icb(df_icb)

        logger.info("[ 2/2 ] Loading {} ICB records...", len(icb_records))
        total_icb = ListingLoader.load_icb_industries(icb_records)

    except Exception as e:
        logger.error("✗ Job Listing Sync thất bại: {}", e)
        raise

    logger.success(
        "✓ Listing Sync hoàn tất — {} symbols, {} ICB records",
        total_symbols, total_icb,
    )
