from sqlalchemy import text

from db.repositories.base import BaseRepository


class FinanceRepository(BaseRepository):
    def _upsert_statement(self, table: str, records: list[dict], unique_cols: str) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                f"""
                INSERT INTO {table}
                    (symbol, period_type, period_label, year, quarter,
                     item_id, item_vn, item_en, value, unit,
                     row_order, hierarchy_level, is_audited, data_source, fetched_at)
                VALUES
                    (:symbol, :period_type, :period_label, :year, :quarter,
                     :item_id, :item_vn, :item_en, :value, :unit,
                     :row_order, :hierarchy_level, :is_audited, :data_source, NOW())
                ON CONFLICT ({unique_cols}) DO UPDATE SET
                    value          = EXCLUDED.value,
                    item_vn        = EXCLUDED.item_vn,
                    item_en        = EXCLUDED.item_en,
                    row_order      = EXCLUDED.row_order,
                    hierarchy_level = EXCLUDED.hierarchy_level,
                    is_audited     = EXCLUDED.is_audited,
                    fetched_at     = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def upsert_income_statement(self, records: list[dict]) -> int:
        return self._upsert_statement(
            "finance.income_statement",
            records,
            "symbol, period_type, period_label, item_id, data_source",
        )

    def upsert_balance_sheet(self, records: list[dict]) -> int:
        return self._upsert_statement(
            "finance.balance_sheet",
            records,
            "symbol, period_type, period_label, item_id, data_source",
        )

    def upsert_cash_flow(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO finance.cash_flow
                    (symbol, period_type, period_label, year, quarter, cash_flow_method,
                     item_id, item_vn, item_en, value, unit,
                     row_order, hierarchy_level, is_audited, data_source, fetched_at)
                VALUES
                    (:symbol, :period_type, :period_label, :year, :quarter, :cash_flow_method,
                     :item_id, :item_vn, :item_en, :value, :unit,
                     :row_order, :hierarchy_level, :is_audited, :data_source, NOW())
                ON CONFLICT (symbol, period_type, period_label, item_id, cash_flow_method, data_source)
                DO UPDATE SET
                    value           = EXCLUDED.value,
                    item_vn         = EXCLUDED.item_vn,
                    item_en         = EXCLUDED.item_en,
                    row_order       = EXCLUDED.row_order,
                    hierarchy_level = EXCLUDED.hierarchy_level,
                    is_audited      = EXCLUDED.is_audited,
                    fetched_at      = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def upsert_financial_ratios(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO finance.financial_ratio
                    (symbol, period_type, period_label, year, quarter,
                     ratio_group, item_id, item_vn, item_en, value, unit,
                     row_order, data_source, fetched_at)
                VALUES
                    (:symbol, :period_type, :period_label, :year, :quarter,
                     :ratio_group, :item_id, :item_vn, :item_en, :value, :unit,
                     :row_order, :data_source, NOW())
                ON CONFLICT (symbol, period_type, period_label, item_id, data_source)
                DO UPDATE SET
                    value      = EXCLUDED.value,
                    ratio_group = EXCLUDED.ratio_group,
                    item_vn    = EXCLUDED.item_vn,
                    item_en    = EXCLUDED.item_en,
                    row_order  = EXCLUDED.row_order,
                    fetched_at = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)
