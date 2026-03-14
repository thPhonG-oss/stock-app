from sqlalchemy import text

from db.repositories.base import BaseRepository


class ListingRepository(BaseRepository):
    def upsert_symbols(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO listing.symbol
                    (symbol, company_name, company_name_en, exchange, asset_type,
                     icb_code, is_active, listing_date, delisting_date,
                     data_source, fetched_at, updated_at)
                VALUES
                    (:symbol, :company_name, :company_name_en, :exchange, :asset_type,
                     :icb_code, :is_active, :listing_date, :delisting_date,
                     :data_source, NOW(), NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    company_name    = EXCLUDED.company_name,
                    company_name_en = EXCLUDED.company_name_en,
                    exchange        = EXCLUDED.exchange,
                    asset_type      = EXCLUDED.asset_type,
                    icb_code        = EXCLUDED.icb_code,
                    is_active       = EXCLUDED.is_active,
                    listing_date    = COALESCE(EXCLUDED.listing_date,
                                              listing.symbol.listing_date),
                    delisting_date  = EXCLUDED.delisting_date,
                    data_source     = EXCLUDED.data_source,
                    updated_at      = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def upsert_icb_industries(self, records: list[dict]) -> int:
        if not records:
            return 0
        self.conn.execute(
            text(
                """
                INSERT INTO listing.icb_industry
                    (icb_code, name_vn, name_en, level, parent_code, data_source, fetched_at)
                VALUES
                    (:icb_code, :name_vn, :name_en, :level, :parent_code,
                     :data_source, NOW())
                ON CONFLICT (icb_code) DO UPDATE SET
                    name_vn     = EXCLUDED.name_vn,
                    name_en     = EXCLUDED.name_en,
                    level       = EXCLUDED.level,
                    parent_code = EXCLUDED.parent_code,
                    fetched_at  = NOW()
                """
            ),
            records,
        )
        self.conn.commit()
        return len(records)

    def get_all_symbols(self, is_active: bool = True) -> list[dict]:
        rows = self.conn.execute(
            text(
                """
                SELECT symbol, company_name, exchange, asset_type, icb_code,
                       is_active, listing_date, data_source
                FROM listing.symbol
                WHERE is_active = :is_active
                ORDER BY exchange, symbol
                """
            ),
            {"is_active": is_active},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_symbols_by_exchange(self, exchange: str) -> list[str]:
        rows = self.conn.execute(
            text(
                "SELECT symbol FROM listing.symbol "
                "WHERE exchange = :exchange AND is_active = TRUE "
                "ORDER BY symbol"
            ),
            {"exchange": exchange},
        ).fetchall()
        return [r[0] for r in rows]
