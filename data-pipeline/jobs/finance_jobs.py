"""
jobs/finance_jobs.py

Job lấy báo cáo tài chính cho tất cả active symbols.
"""

import time
from loguru import logger
from config.settings import settings
from extractors.finance_extractor import FinanceExtractor
from transformers.finance_transformer import FinanceTransformer
from loaders.finance_loader import FinanceLoader
from loaders.base_loader import BaseLoader
from db.repositories.listing_repo import ListingRepository


def job_fetch_financial_statements():
    """
    Job: Lấy báo cáo tài chính (income, balance, cash, ratio) cho tất cả symbols.

    Lịch chạy: mỗi tháng ngày 1, lúc 9:00 AM
    """
    logger.info("═" * 60)
    logger.info("▶ Bắt đầu job: Fetch Financial Statements")
    logger.info("═" * 60)

    # Lấy danh sách symbols
    with BaseLoader.connect() as conn:
        repo = ListingRepository(conn)
        symbols = repo.get_all_symbols()

    if not symbols:
        logger.warning("Không có symbols nào. Chạy listing sync trước!")
        return

    batch_size = settings.BATCH_SIZE
    total_income = 0
    total_balance = 0
    total_cash = 0
    total_ratio = 0
    errors = 0

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i: i + batch_size]
        logger.info("Processing batch {}/{}", i // batch_size + 1,
                     (len(symbols) + batch_size - 1) // batch_size)

        for sym_row in batch:
            symbol = sym_row["symbol"] if isinstance(sym_row, dict) else sym_row

            try:
                # ── Income Statement ──────────────────────────────────
                df_is = FinanceExtractor.extract_income_statement(symbol)
                is_records = FinanceTransformer.transform_income_statement(df_is, symbol)
                total_income += FinanceLoader.load_income_statement(is_records)

                # ── Balance Sheet ─────────────────────────────────────
                df_bs = FinanceExtractor.extract_balance_sheet(symbol)
                bs_records = FinanceTransformer.transform_balance_sheet(df_bs, symbol)
                total_balance += FinanceLoader.load_balance_sheet(bs_records)

                # ── Cash Flow ─────────────────────────────────────────
                df_cf = FinanceExtractor.extract_cash_flow(symbol)
                cf_records = FinanceTransformer.transform_cash_flow(df_cf, symbol)
                total_cash += FinanceLoader.load_cash_flow(cf_records)

                # ── Financial Ratios ──────────────────────────────────
                df_rat = FinanceExtractor.extract_ratio(symbol)
                rat_records = FinanceTransformer.transform_ratio(df_rat, symbol)
                total_ratio += FinanceLoader.load_financial_ratios(rat_records)

            except Exception as e:
                logger.warning("Lỗi BCTC cho {}: {}", symbol, e)
                errors += 1
                continue

            time.sleep(0.5)  # Rate limiting

    logger.success(
        "✓ Financial Statements hoàn tất — IS:{}, BS:{}, CF:{}, Ratio:{}, Errors:{}",
        total_income, total_balance, total_cash, total_ratio, errors,
    )
