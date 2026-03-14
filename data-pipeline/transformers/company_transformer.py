"""
transformers/company_transformer.py

Chuyển đổi DataFrame công ty từ vnstock → list[dict] cho company.* tables.
"""

import json
import pandas as pd
from loguru import logger
from config.settings import settings


class CompanyTransformer:
    """Chuyển đổi dữ liệu company từ DataFrame sang records cho DB."""

    @classmethod
    def transform_profile(cls, df: pd.DataFrame, symbol: str) -> dict | None:
        """
        Chuyển Company.overview() DataFrame → 1 record dict cho CompanyRepository.insert_profile().
        vnstock trả về 1 row (hoặc Series) chứa thông tin tổng quan.
        """
        if df is None or df.empty:
            return None

        source = settings.VNSTOCK_SOURCE

        # overview() có thể trả về DataFrame 1 dòng hoặc nhiều dòng
        if isinstance(df, pd.Series):
            row = df
        else:
            row = df.iloc[0] if len(df) > 0 else None
            if row is None:
                return None

        # Lưu toàn bộ raw data dưới dạng JSON
        try:
            raw_data = json.dumps(row.to_dict(), default=str, ensure_ascii=False)
        except Exception:
            raw_data = "{}"

        record = {
            "symbol": symbol.upper(),
            "company_name": row.get("company_name", row.get("organ_name")),
            "company_name_en": row.get("company_name_en", row.get("en_organ_name")),
            "exchange": str(row.get("exchange", "UNKNOWN")).upper(),
            "icb_code": row.get("icb_code"),
            "founded_date": _parse_date(row.get("founded_date", row.get("established_date"))),
            "listing_date": _parse_date(row.get("listing_date")),
            "charter_capital": _safe_num(row.get("charter_capital")),
            "issued_shares": _safe_int(row.get("issued_shares", row.get("outstanding_shares"))),
            "num_employees": _safe_int(row.get("no_employees", row.get("num_employees"))),
            "website": row.get("website"),
            "tax_code": row.get("tax_code"),
            "address": row.get("address"),
            "phone": row.get("phone"),
            "business_model": row.get("business_model", row.get("company_profile")),
            "description": row.get("description", row.get("company_profile")),
            "stock_type": row.get("stock_type", "stock"),
            "raw_data": raw_data,
            "data_source": source,
        }

        logger.debug("Transformed profile for {}", symbol)
        return record

    @classmethod
    def transform_shareholders(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """Chuyển Company.shareholders() → records cho CompanyRepository.upsert_shareholders()."""
        if df is None or df.empty:
            return []

        source = settings.VNSTOCK_SOURCE
        records = []

        for _, row in df.iterrows():
            records.append({
                "symbol": symbol.upper(),
                "shareholder_name": row.get("share_holder", row.get("shareholder_name", "Unknown")),
                "shares": _safe_int(row.get("share_own", row.get("shares"))),
                "ownership_pct": _safe_num(row.get("share_own_percent", row.get("ownership_pct"))),
                "report_date": _parse_date(row.get("report_date")),
                "data_source": source,
            })

        logger.debug("Transformed {} shareholders for {}", len(records), symbol)
        return records

    @classmethod
    def transform_officers(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """Chuyển Company.officers() → records cho CompanyRepository.upsert_officers()."""
        if df is None or df.empty:
            return []

        source = settings.VNSTOCK_SOURCE
        records = []

        for _, row in df.iterrows():
            records.append({
                "symbol": symbol.upper(),
                "full_name": row.get("officer_name", row.get("full_name", "Unknown")),
                "position_vn": row.get("officer_position", row.get("position_vn")),
                "position_en": row.get("officer_position_en", row.get("position_en")),
                "from_date": _parse_date(row.get("from_date")),
                "to_date": _parse_date(row.get("to_date")),
                "is_active": bool(row.get("is_active", True)),
                "owned_shares": _safe_int(row.get("officer_own_percent")),
                "ownership_pct": _safe_num(row.get("officer_own_percent")),
                "data_source": source,
            })

        logger.debug("Transformed {} officers for {}", len(records), symbol)
        return records

    @classmethod
    def transform_events(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """Chuyển Company.events() → records cho CompanyRepository.upsert_events()."""
        if df is None or df.empty:
            return []

        source = settings.VNSTOCK_SOURCE
        records = []

        for _, row in df.iterrows():
            try:
                raw_data = json.dumps(row.to_dict(), default=str, ensure_ascii=False)
            except Exception:
                raw_data = "{}"

            records.append({
                "symbol": symbol.upper(),
                "event_type": _safe_int(row.get("event_type_id", row.get("event_type", 5))) or 5,
                "event_type_name": row.get("event_type_name", row.get("event_name")),
                "event_date": _parse_date(row.get("event_date", row.get("notify_date"))),
                "ex_date": _parse_date(row.get("ex_date", row.get("exer_date"))),
                "record_date": _parse_date(row.get("record_date")),
                "payment_date": _parse_date(row.get("payment_date")),
                "title": row.get("event_title", row.get("event_desc", "")),
                "description": row.get("event_desc", row.get("description")),
                "value": _safe_num(row.get("value")),
                "raw_data": raw_data,
                "data_source": source,
            })

        logger.debug("Transformed {} events for {}", len(records), symbol)
        return records


def _parse_date(val):
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def _safe_num(val):
    if val is None:
        return None
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None:
        return None
    try:
        f = float(val)
        return int(f) if pd.notna(f) else None
    except (ValueError, TypeError):
        return None
