from sqlalchemy import text

from db.repositories.base import BaseRepository


class CompanyRepository(BaseRepository):
    def insert_profile(self, record: dict) -> None:
        """Insert a new company profile snapshot (versioned by fetched_at)."""
        self.conn.execute(
            text(
                """
                INSERT INTO company.profile
                    (symbol, company_name, company_name_en, exchange, icb_code,
                     founded_date, listing_date, charter_capital, issued_shares,
                     num_employees, website, tax_code, address, phone,
                     business_model, description, stock_type, raw_data,
                     data_source, fetched_at)
                VALUES
                    (:symbol, :company_name, :company_name_en, :exchange, :icb_code,
                     :founded_date, :listing_date, :charter_capital, :issued_shares,
                     :num_employees, :website, :tax_code, :address, :phone,
                     :business_model, :description, :stock_type, :raw_data::jsonb,
                     :data_source, NOW())
                ON CONFLICT (symbol, data_source, fetched_at) DO NOTHING
                """
            ),
            record,
        )
        self.conn.commit()

    def upsert_shareholders(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO company.shareholder
                    (symbol, shareholder_name, shares, ownership_pct,
                     report_date, data_source, fetched_at)
                VALUES
                    (:symbol, :shareholder_name, :shares, :ownership_pct,
                     :report_date, :data_source, NOW())
                ON CONFLICT (symbol, shareholder_name, report_date, data_source)
                DO UPDATE SET
                    shares        = EXCLUDED.shares,
                    ownership_pct = EXCLUDED.ownership_pct,
                    fetched_at    = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def upsert_officers(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO company.officer
                    (symbol, full_name, position_vn, position_en,
                     from_date, to_date, is_active,
                     owned_shares, ownership_pct, data_source, fetched_at)
                VALUES
                    (:symbol, :full_name, :position_vn, :position_en,
                     :from_date, :to_date, :is_active,
                     :owned_shares, :ownership_pct, :data_source, NOW())
                ON CONFLICT (symbol, full_name, from_date, data_source)
                DO UPDATE SET
                    position_vn   = EXCLUDED.position_vn,
                    position_en   = EXCLUDED.position_en,
                    to_date       = EXCLUDED.to_date,
                    is_active     = EXCLUDED.is_active,
                    owned_shares  = EXCLUDED.owned_shares,
                    ownership_pct = EXCLUDED.ownership_pct,
                    fetched_at    = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def upsert_subsidiaries(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO company.subsidiary
                    (parent_symbol, sub_name, charter_capital, ownership_pct,
                     currency, relation_type, effective_date, data_source, fetched_at)
                VALUES
                    (:parent_symbol, :sub_name, :charter_capital, :ownership_pct,
                     :currency, :relation_type, :effective_date, :data_source, NOW())
                ON CONFLICT (parent_symbol, sub_name, data_source, fetched_at)
                DO NOTHING
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def upsert_events(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO company.event
                    (symbol, event_type, event_type_name, event_date, ex_date,
                     record_date, payment_date, title, description, value,
                     raw_data, data_source, fetched_at)
                VALUES
                    (:symbol, :event_type, :event_type_name, :event_date, :ex_date,
                     :record_date, :payment_date, :title, :description, :value,
                     :raw_data::jsonb, :data_source, NOW())
                ON CONFLICT (symbol, event_type, event_date, title, data_source)
                DO NOTHING
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)
