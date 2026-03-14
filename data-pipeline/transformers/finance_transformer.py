"""
transformers/finance_transformer.py

Chuyển đổi DataFrame BCTC từ vnstock → EAV format records cho finance.* tables.

vnstock Finance trả về dạng wide table (columns = periods, rows = line items).
Ta cần pivot → EAV (Entity-Attribute-Value):
  symbol | period_type | period_label | year | quarter | item_id | item_vn | item_en | value
"""

import re
import pandas as pd
from loguru import logger
from config.settings import settings


class FinanceTransformer:
    """Chuyển đổi BCTC từ wide → EAV format."""

    @classmethod
    def transform_income_statement(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """Chuyển income_statement wide DataFrame → EAV records."""
        return cls._wide_to_eav(df, symbol, "finance.income_statement")

    @classmethod
    def transform_balance_sheet(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """Chuyển balance_sheet wide DataFrame → EAV records."""
        return cls._wide_to_eav(df, symbol, "finance.balance_sheet")

    @classmethod
    def transform_cash_flow(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """Chuyển cash_flow wide DataFrame → EAV records."""
        records = cls._wide_to_eav(df, symbol, "finance.cash_flow")
        # Thêm cash_flow_method mặc định
        for r in records:
            r["cash_flow_method"] = "indirect"
        return records

    @classmethod
    def transform_ratio(cls, df: pd.DataFrame, symbol: str) -> list[dict]:
        """Chuyển ratio wide DataFrame → EAV records."""
        records = cls._wide_to_eav(df, symbol, "finance.financial_ratio")
        for r in records:
            r["ratio_group"] = r.get("ratio_group", "general")
        return records

    @classmethod
    def _wide_to_eav(
        cls, df: pd.DataFrame, symbol: str, target_table: str
    ) -> list[dict]:
        """
        Chuyển wide table từ vnstock → EAV records.

        vnstock Finance trả về DataFrame với:
        - Cột đầu tiên chứa tên chỉ tiêu (item names)
        - Các cột còn lại là periods (VD: '2024', '2024-Q1', ...)
        - Giá trị = số liệu tài chính

        Lưu ý: Format có thể khác nhau tuỳ source (VCI/KBS/TCBS).
        Ta xử lý cả 2 trường hợp:
          1. Index = item names, Columns = periods
          2. Columns include 'Meta/Attribute' + period columns
        """
        if df is None or df.empty:
            return []

        source = settings.VNSTOCK_SOURCE
        records = []
        row_order = 0

        # Xử lý nhiều format khác nhau của vnstock
        try:
            # Nếu DataFrame có dạng rows = items, columns = periods
            for idx, row in df.iterrows():
                row_order += 1
                # Tên chỉ tiêu - có thể từ index hoặc cột đặc biệt
                item_name = str(idx) if not isinstance(idx, int) else str(row.iloc[0])
                item_id = _to_snake_case(item_name)

                # Duyệt qua các cột period
                for col in df.columns:
                    col_str = str(col)
                    # Bỏ qua cột metadata (không phải period)
                    if col_str.lower() in ("", "meta", "attribute", "chỉ tiêu", "item"):
                        continue

                    val = row.get(col)
                    if val is None or (isinstance(val, float) and pd.isna(val)):
                        continue

                    period_label, year, quarter, period_type = _parse_period(col_str)
                    if period_label is None:
                        continue

                    try:
                        value = float(val)
                    except (ValueError, TypeError):
                        continue

                    record = {
                        "symbol": symbol.upper(),
                        "period_type": period_type,
                        "period_label": period_label,
                        "year": year,
                        "quarter": quarter,
                        "item_id": item_id[:120],
                        "item_vn": None,
                        "item_en": item_name[:500] if item_name else None,
                        "value": value,
                        "unit": "billion_vnd",
                        "row_order": row_order,
                        "hierarchy_level": 0,
                        "is_audited": False,
                        "data_source": source,
                    }

                    # Thêm ratio_group cho financial_ratio
                    if "ratio" in target_table:
                        record["ratio_group"] = "general"

                    records.append(record)

        except Exception as e:
            logger.warning("Lỗi transform {} cho {}: {}", target_table, symbol, e)

        logger.debug("Transformed {} EAV records for {} ({})", len(records), symbol, target_table)
        return records


def _to_snake_case(name: str) -> str:
    """Chuyển tên chỉ tiêu → snake_case item_id."""
    if not name:
        return "unknown"
    # Remove dấu tiếng Việt cơ bản và ký tự đặc biệt
    s = re.sub(r"[^\w\s]", "", name.strip())
    s = re.sub(r"\s+", "_", s)
    s = s.lower()
    return s[:120] if s else "unknown"


def _parse_period(col: str) -> tuple:
    """
    Parse period label từ tên cột.
    Returns: (period_label, year, quarter, period_type) hoặc (None,...) nếu không parse được.

    Hỗ trợ các format:
      - '2024' → ('2024', 2024, None, 'year')
      - '2024-Q1' → ('2024-Q1', 2024, 1, 'quarter')
      - 'Q1-2024' → ('2024-Q1', 2024, 1, 'quarter')
      - '2024Q1' → ('2024-Q1', 2024, 1, 'quarter')
    """
    col = str(col).strip()

    # Thử match 2024-Q1 hoặc Q1-2024
    m = re.match(r"(\d{4})[_\-]?Q(\d)", col, re.IGNORECASE)
    if m:
        year = int(m.group(1))
        quarter = int(m.group(2))
        return f"{year}-Q{quarter}", year, quarter, "quarter"

    m = re.match(r"Q(\d)[_\-]?(\d{4})", col, re.IGNORECASE)
    if m:
        quarter = int(m.group(1))
        year = int(m.group(2))
        return f"{year}-Q{quarter}", year, quarter, "quarter"

    # Thử match năm đơn thuần
    m = re.match(r"^(\d{4})$", col)
    if m:
        year = int(m.group(1))
        if 1990 <= year <= 2099:
            return str(year), year, None, "year"

    return None, None, None, None
