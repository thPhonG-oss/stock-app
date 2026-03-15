"""
backfill.py

CLI script để chạy thủ công từng job với date range tùy chọn.
Dùng để verify dữ liệu hoặc backfill lịch sử.

Usage examples:
    # OHLCV cho 3 symbols trong 1 tuần
    python backfill.py ohlcv --start 2025-03-01 --end 2025-03-07 --symbols VIC VHM ACB

    # OHLCV cho tất cả symbols từ đầu năm
    python backfill.py ohlcv --start 2025-01-01

    # Foreign flow cho 2 symbols
    python backfill.py foreign-flow --start 2025-03-01 --end 2025-03-10 --symbols VIC VHM

    # Sync listing (không cần date)
    python backfill.py listing

    # Company profiles cho một số symbols
    python backfill.py company --symbols VIC VHM ACB

    # Báo cáo tài chính
    python backfill.py finance --symbols VIC
"""

import argparse
import sys
from datetime import date

from config import setup_logging, settings
from loguru import logger


def run_ohlcv(args):
    from jobs.market_jobs import job_fetch_ohlcv_daily
    symbols = args.symbols or None
    start = args.start
    end = args.end or str(date.today())
    logger.info("Backfill OHLCV | start={} end={} symbols={}", start, end, symbols or "ALL")
    job_fetch_ohlcv_daily(start_date=start, end_date=end, symbols_filter=symbols)


def run_foreign_flow(args):
    from jobs.trading_jobs import job_fetch_foreign_flow
    symbols = args.symbols or None
    start = args.start
    end = args.end or str(date.today())
    logger.info("Backfill Foreign Flow | start={} end={} symbols={}", start, end, symbols or "ALL")
    job_fetch_foreign_flow(start_date=start, end_date=end, symbols_filter=symbols)


def run_listing(args):
    from jobs.listing_jobs import job_sync_listing
    logger.info("Running Listing Sync...")
    job_sync_listing()


def run_company(args):
    from jobs.company_jobs import job_fetch_company_profiles
    if args.symbols:
        # Patch the repo call via symbols_filter workaround
        logger.info("Company Profiles | symbols={}", args.symbols)
        _run_company_filtered(args.symbols)
    else:
        logger.info("Company Profiles | ALL symbols")
        job_fetch_company_profiles()


def _run_company_filtered(symbols_filter: list[str]):
    """Run company job for a subset of symbols."""
    import time
    from extractors.company_extractor import CompanyExtractor
    from transformers.company_transformer import CompanyTransformer
    from loaders.company_loader import CompanyLoader

    symbols_upper = [s.upper() for s in symbols_filter]
    total_profiles = total_sh = total_off = total_evt = errors = 0

    for symbol in symbols_upper:
        try:
            df_ov = CompanyExtractor.extract_overview(symbol)
            profile = CompanyTransformer.transform_profile(df_ov, symbol)
            CompanyLoader.load_profile(profile)
            if profile:
                total_profiles += 1

            df_sh = CompanyExtractor.extract_shareholders(symbol)
            sh_records = CompanyTransformer.transform_shareholders(df_sh, symbol)
            CompanyLoader.load_shareholders(sh_records)
            total_sh += len(sh_records)

            df_off = CompanyExtractor.extract_officers(symbol)
            off_records = CompanyTransformer.transform_officers(df_off, symbol)
            CompanyLoader.load_officers(off_records)
            total_off += len(off_records)

            df_evt = CompanyExtractor.extract_events(symbol)
            evt_records = CompanyTransformer.transform_events(df_evt, symbol)
            CompanyLoader.load_events(evt_records)
            total_evt += len(evt_records)

        except Exception as e:
            logger.warning("Lỗi company data cho {}: {}", symbol, e)
            errors += 1
            continue

        time.sleep(0.5)

    logger.success(
        "✓ Company done — {} profiles, {} shareholders, {} officers, {} events, {} errors",
        total_profiles, total_sh, total_off, total_evt, errors,
    )


def run_finance(args):
    from jobs.finance_jobs import job_fetch_financial_statements
    if args.symbols:
        logger.info("Financial Statements | symbols={}", args.symbols)
        _run_finance_filtered(args.symbols)
    else:
        logger.info("Financial Statements | ALL symbols")
        job_fetch_financial_statements()


def _run_finance_filtered(symbols_filter: list[str]):
    """Run finance job for a subset of symbols."""
    import time
    from extractors.finance_extractor import FinanceExtractor
    from transformers.finance_transformer import FinanceTransformer
    from loaders.finance_loader import FinanceLoader

    symbols_upper = [s.upper() for s in symbols_filter]
    total_is = total_bs = total_cf = total_rat = errors = 0

    for symbol in symbols_upper:
        try:
            df_is = FinanceExtractor.extract_income_statement(symbol)
            is_records = FinanceTransformer.transform_income_statement(df_is, symbol)
            total_is += FinanceLoader.load_income_statement(is_records)

            df_bs = FinanceExtractor.extract_balance_sheet(symbol)
            bs_records = FinanceTransformer.transform_balance_sheet(df_bs, symbol)
            total_bs += FinanceLoader.load_balance_sheet(bs_records)

            df_cf = FinanceExtractor.extract_cash_flow(symbol)
            cf_records = FinanceTransformer.transform_cash_flow(df_cf, symbol)
            total_cf += FinanceLoader.load_cash_flow(cf_records)

            df_rat = FinanceExtractor.extract_ratio(symbol)
            rat_records = FinanceTransformer.transform_ratio(df_rat, symbol)
            total_rat += FinanceLoader.load_financial_ratios(rat_records)

        except Exception as e:
            logger.warning("Lỗi BCTC cho {}: {}", symbol, e)
            errors += 1
            continue

        time.sleep(0.5)

    logger.success(
        "✓ Finance done — IS:{}, BS:{}, CF:{}, Ratio:{}, Errors:{}",
        total_is, total_bs, total_cf, total_rat, errors,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill",
        description="Chạy thủ công các pipeline jobs với date range tùy chọn",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="job", required=True)

    # ── ohlcv ────────────────────────────────────────────────────────
    p_ohlcv = sub.add_parser("ohlcv", help="Fetch OHLCV daily data")
    p_ohlcv.add_argument("--start", required=True, metavar="YYYY-MM-DD",
                         help="Ngày bắt đầu (bắt buộc)")
    p_ohlcv.add_argument("--end", metavar="YYYY-MM-DD", default=None,
                         help="Ngày kết thúc (mặc định: hôm nay)")
    p_ohlcv.add_argument("--symbols", nargs="+", metavar="SYMBOL",
                         help="Danh sách symbols (ví dụ: VIC VHM ACB). Mặc định: tất cả")
    p_ohlcv.set_defaults(func=run_ohlcv)

    # ── foreign-flow ─────────────────────────────────────────────────
    p_ff = sub.add_parser("foreign-flow", help="Fetch foreign flow data")
    p_ff.add_argument("--start", required=True, metavar="YYYY-MM-DD",
                      help="Ngày bắt đầu (bắt buộc)")
    p_ff.add_argument("--end", metavar="YYYY-MM-DD", default=None,
                      help="Ngày kết thúc (mặc định: hôm nay)")
    p_ff.add_argument("--symbols", nargs="+", metavar="SYMBOL",
                      help="Danh sách symbols. Mặc định: tất cả")
    p_ff.set_defaults(func=run_foreign_flow)

    # ── listing ──────────────────────────────────────────────────────
    p_listing = sub.add_parser("listing", help="Sync listing symbols + ICB")
    p_listing.set_defaults(func=run_listing)

    # ── company ──────────────────────────────────────────────────────
    p_company = sub.add_parser("company", help="Fetch company profiles")
    p_company.add_argument("--symbols", nargs="+", metavar="SYMBOL",
                           help="Danh sách symbols. Mặc định: tất cả")
    p_company.set_defaults(func=run_company)

    # ── finance ──────────────────────────────────────────────────────
    p_finance = sub.add_parser("finance", help="Fetch financial statements")
    p_finance.add_argument("--symbols", nargs="+", metavar="SYMBOL",
                           help="Danh sách symbols. Mặc định: tất cả")
    p_finance.set_defaults(func=run_finance)

    return parser


if __name__ == "__main__":
    setup_logging()
    logger.info("Backfill tool | DB: {}:{}/{}", settings.DB_HOST, settings.DB_PORT, settings.DB_NAME)

    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
