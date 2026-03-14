"""
jobs/company_jobs.py

Job lấy thông tin công ty cho tất cả active symbols.
"""

import time
from loguru import logger
from config.settings import settings
from extractors.company_extractor import CompanyExtractor
from transformers.company_transformer import CompanyTransformer
from loaders.company_loader import CompanyLoader
from loaders.base_loader import BaseLoader
from db.repositories.listing_repo import ListingRepository


def job_fetch_company_profiles():
    """
    Job: Lấy company profiles (overview, shareholders, officers, events).

    Lịch chạy: mỗi tuần Thứ 2 lúc 8:00 AM
    """
    logger.info("═" * 60)
    logger.info("▶ Bắt đầu job: Fetch Company Profiles")
    logger.info("═" * 60)

    # Lấy danh sách symbols
    with BaseLoader.connect() as conn:
        repo = ListingRepository(conn)
        symbols = repo.get_all_symbols()

    if not symbols:
        logger.warning("Không có symbols nào. Chạy listing sync trước!")
        return

    batch_size = settings.BATCH_SIZE
    total_profiles = 0
    total_shareholders = 0
    total_officers = 0
    total_events = 0
    errors = 0

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i: i + batch_size]
        logger.info("Processing batch {}/{}", i // batch_size + 1,
                     (len(symbols) + batch_size - 1) // batch_size)

        for sym_row in batch:
            symbol = sym_row["symbol"] if isinstance(sym_row, dict) else sym_row

            try:
                # ── Overview / Profile ────────────────────────────────
                df_ov = CompanyExtractor.extract_overview(symbol)
                profile = CompanyTransformer.transform_profile(df_ov, symbol)
                CompanyLoader.load_profile(profile)
                if profile:
                    total_profiles += 1

                # ── Shareholders ──────────────────────────────────────
                df_sh = CompanyExtractor.extract_shareholders(symbol)
                sh_records = CompanyTransformer.transform_shareholders(df_sh, symbol)
                CompanyLoader.load_shareholders(sh_records)
                total_shareholders += len(sh_records)

                # ── Officers ──────────────────────────────────────────
                df_off = CompanyExtractor.extract_officers(symbol)
                off_records = CompanyTransformer.transform_officers(df_off, symbol)
                CompanyLoader.load_officers(off_records)
                total_officers += len(off_records)

                # ── Events ────────────────────────────────────────────
                df_evt = CompanyExtractor.extract_events(symbol)
                evt_records = CompanyTransformer.transform_events(df_evt, symbol)
                CompanyLoader.load_events(evt_records)
                total_events += len(evt_records)

            except Exception as e:
                logger.warning("Lỗi company data cho {}: {}", symbol, e)
                errors += 1
                continue

            time.sleep(0.5)  # Rate limiting

    logger.success(
        "✓ Company Profiles hoàn tất — {} profiles, {} shareholders, "
        "{} officers, {} events, {} errors",
        total_profiles, total_shareholders, total_officers, total_events, errors,
    )
