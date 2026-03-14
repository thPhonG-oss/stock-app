-- =============================================================================
--  Stock App Data Pipeline — PostgreSQL Schema
--  Database : stockapp
--  Revised  : 2026-03-14  (full Vietnamese stock market scope)
--
--  Schema layout:
--    listing     → master symbol list, ICB hierarchy, groups, calendar, changes
--    market      → price bars (daily + intraday), tick trades, order book,
--                  index OHLCV, market breadth, trading halts, price adjustments
--    derivatives → futures contract profiles, covered warrant profiles
--    company     → profiles, shareholders, officers, events, news, splits
--    finance     → BCTC in EAV format (income, balance, cash flow, ratios)
--    trading     → foreign flow, block/odd-lot trades, daily stats, price board
--    index_data  → index registry and constituents
--    fund        → mutual fund list, NAV history, holdings
--    macro       → exchange rates, GDP/CPI/FDI and economic indicators
--    commodity   → gold, gasoline/oil, steel, fertilizer
--    etl         → collection tiers, symbol config, job registry,
--                  run logs, freshness tracker, pipeline state
--
--  Scale target:
--    ~1,785 instruments  (HOSE ~400 + HNX ~300 + UPCOM ~700
--                         + Derivatives ~30 + CW ~120 + ETF ~35 + Bonds ~200)
--    OHLCV 1D  : ~446K rows/year       → annual partitions
--    OHLCV 1m  : ~187M rows/year       → monthly partitions
--    Tick data : ~3.6M rows/day        → daily partitions (pg_partman recommended)
--    Storage   : ~35 GB/yr (intraday) + ~125 GB/yr (ticks)
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
--  SHARED ENUM TYPES  (public schema — imported by all other schemas)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TYPE public.interval_type AS ENUM (
    '1m', '5m', '15m', '30m', '1H', '4h', '1D', '1W', '1M'
);

-- Sub-daily intervals group (used to route to ohlcv_intraday)
-- '1m','5m','15m','30m','1H','4h'
-- Daily+ intervals group (used to route to ohlcv_daily)
-- '1D','1W','1M'

CREATE TYPE public.exchange_type AS ENUM (
    'HOSE', 'HNX', 'UPCOM', 'HNX_DERIVATIVE', 'UNKNOWN'
);

CREATE TYPE public.asset_type AS ENUM (
    'stock', 'etf', 'cw', 'futures', 'bond', 'index', 'unknown'
);

CREATE TYPE public.match_side AS ENUM (
    'buy', 'sell', 'atc', 'ato', 'unknown'
);

CREATE TYPE public.period_type AS ENUM (
    'quarter', 'year'
);

CREATE TYPE public.warrant_type AS ENUM (
    'call', 'put'
);


-- =============================================================================
--  SCHEMA: listing
--  Master symbol list, ICB hierarchy, symbol groups,
--  trading calendar, and symbol change history
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS listing;

-- -----------------------------------------------------------------------------
-- listing.symbol
-- Source : Listing.all_symbols(), Listing.symbols_by_exchange()
-- Master reference table for all tradable instruments on Vietnamese exchanges.
-- Upsert : ON CONFLICT (symbol) DO UPDATE SET updated_at = NOW(), ...
-- -----------------------------------------------------------------------------
CREATE TABLE listing.symbol (
    symbol          VARCHAR(20)             NOT NULL,
    company_name    TEXT,
    company_name_en TEXT,
    exchange        public.exchange_type    NOT NULL DEFAULT 'UNKNOWN',
    asset_type      public.asset_type       NOT NULL DEFAULT 'stock',
    icb_code        VARCHAR(20),            -- → listing.icb_industry
    is_active       BOOLEAN                 NOT NULL DEFAULT TRUE,
    listing_date    DATE,
    delisting_date  DATE,
    data_source     VARCHAR(20)             NOT NULL,
    fetched_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol)
);

CREATE INDEX idx_symbol_exchange    ON listing.symbol (exchange, is_active);
CREATE INDEX idx_symbol_asset_type  ON listing.symbol (asset_type, is_active);
CREATE INDEX idx_symbol_icb         ON listing.symbol (icb_code) WHERE icb_code IS NOT NULL;

-- -----------------------------------------------------------------------------
-- listing.icb_industry
-- Source : Listing.industries_icb()
-- ICB 4-level hierarchy: Industry(1) → Supersector(2) → Sector(3) → Subsector(4)
-- Self-referencing via parent_code.
-- -----------------------------------------------------------------------------
CREATE TABLE listing.icb_industry (
    icb_code    VARCHAR(20)     NOT NULL,
    name_vn     TEXT,
    name_en     TEXT,
    level       SMALLINT        NOT NULL CHECK (level BETWEEN 1 AND 4),
    parent_code VARCHAR(20),                -- NULL for level-1 industries
    data_source VARCHAR(20)     NOT NULL,
    fetched_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (icb_code)
);

-- -----------------------------------------------------------------------------
-- listing.symbol_group
-- Source : Listing.symbols_by_group()
-- Many-to-many: a symbol can be in VN30 and VN100 simultaneously.
-- group_code examples: 'VN30', 'HNX30', 'VNMIDCAP', 'VNSMALLCAP', 'UPCOM',
--                      'ETF', 'CW', 'BOND', 'VN100', 'VNALLSHARE'
-- -----------------------------------------------------------------------------
CREATE TABLE listing.symbol_group (
    symbol          VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    group_code      VARCHAR(20)     NOT NULL,
    group_name      TEXT,
    effective_date  DATE,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, group_code, effective_date)
);

CREATE INDEX idx_sg_group   ON listing.symbol_group (group_code);
CREATE INDEX idx_sg_symbol  ON listing.symbol_group (symbol);

-- -----------------------------------------------------------------------------
-- listing.trading_calendar
-- Official trading days and sessions per exchange.
-- Used by the pipeline to: detect data gaps, skip fetching on holidays,
-- and schedule jobs correctly.
-- Source : Manually seeded + updated from market announcements.
-- -----------------------------------------------------------------------------
CREATE TABLE listing.trading_calendar (
    calendar_date   DATE                    NOT NULL,
    exchange        public.exchange_type    NOT NULL,
    is_trading_day  BOOLEAN                 NOT NULL DEFAULT TRUE,
    session_open    TIME                    DEFAULT '09:00:00',
    session_close   TIME                    DEFAULT '15:00:00',
    note            TEXT,                   -- e.g., 'Tết Nguyên Đán', 'Half day'
    PRIMARY KEY (calendar_date, exchange)
);

CREATE INDEX idx_calendar_trading ON listing.trading_calendar (exchange, calendar_date DESC)
    WHERE is_trading_day = TRUE;

-- -----------------------------------------------------------------------------
-- listing.symbol_change
-- Tracks renames, delistings, transfers, and mergers.
-- Critical for maintaining historical price continuity across the entire market.
-- -----------------------------------------------------------------------------
CREATE TABLE listing.symbol_change (
    id              SERIAL          PRIMARY KEY,
    old_symbol      VARCHAR(20)     NOT NULL,
    new_symbol      VARCHAR(20),                -- NULL if delisted/merged
    change_date     DATE            NOT NULL,
    change_type     VARCHAR(20)     NOT NULL,   -- 'rename' | 'delist' | 'merge' | 'transfer'
    note            TEXT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_symbol_change_old  ON listing.symbol_change (old_symbol, change_date DESC);
CREATE INDEX idx_symbol_change_new  ON listing.symbol_change (new_symbol, change_date DESC)
    WHERE new_symbol IS NOT NULL;


-- =============================================================================
--  SCHEMA: market
--  All price and volume data:
--    ohlcv_daily     — daily/weekly/monthly bars  (partition by YEAR)
--    ohlcv_intraday  — sub-daily bars 1m-4h        (partition by MONTH)
--    intraday_trade  — raw tick matches             (partition by DAY, pg_partman)
--    order_book_snapshot — bid/ask depth snapshots
--    index_ohlcv     — index price series (VNINDEX, VN30, HNX30…)
--    market_breadth  — daily advances/declines/volume for each exchange
--    trading_halt    — stock halt and resume events
--    price_adjustment — corporate action adjustment factors
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS market;

-- ──────────────────────────────────────────────────────────────────────────────
-- market.ohlcv_daily
-- OHLCV bars for intervals: 1D, 1W, 1M  (all equity, ETF, CW, bond symbols)
-- Source : Quote.history(symbol, start, end, interval='1D'|'1W'|'1M')
-- Upsert : ON CONFLICT (symbol, interval, traded_at) DO NOTHING
-- Partitioned RANGE by traded_at — annual partitions (446K rows/year @ 1785 symbols)
-- Added `exchange` column for efficient market-wide queries without joining listing.symbol
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.ohlcv_daily (
    symbol              VARCHAR(20)             NOT NULL,
    interval            public.interval_type    NOT NULL CHECK (interval IN ('1D','1W','1M')),
    traded_at           TIMESTAMPTZ             NOT NULL,   -- bar date at midnight Asia/Ho_Chi_Minh
    exchange            public.exchange_type    NOT NULL DEFAULT 'UNKNOWN',
    open                NUMERIC(18, 4)          NOT NULL,
    high                NUMERIC(18, 4)          NOT NULL,
    low                 NUMERIC(18, 4)          NOT NULL,
    close               NUMERIC(18, 4)          NOT NULL,
    volume              BIGINT                  NOT NULL DEFAULT 0,
    value               NUMERIC(24, 0),                     -- total traded value VND
    -- Extended fields (available with get_all=True from KBS/VCI)
    reference_price     NUMERIC(18, 4),
    ceiling_price       NUMERIC(18, 4),
    floor_price         NUMERIC(18, 4),
    foreign_buy_vol     BIGINT,
    foreign_sell_vol    BIGINT,
    foreign_net_vol     BIGINT,
    put_through_vol     BIGINT,
    put_through_val     NUMERIC(24, 0),
    total_trades        INT,
    -- Metadata
    data_source         VARCHAR(20)             NOT NULL,
    created_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, interval, traded_at)
) PARTITION BY RANGE (traded_at);

CREATE TABLE market.ohlcv_daily_2022 PARTITION OF market.ohlcv_daily
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE market.ohlcv_daily_2023 PARTITION OF market.ohlcv_daily
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE market.ohlcv_daily_2024 PARTITION OF market.ohlcv_daily
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE market.ohlcv_daily_2025 PARTITION OF market.ohlcv_daily
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE market.ohlcv_daily_2026 PARTITION OF market.ohlcv_daily
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE market.ohlcv_daily_future PARTITION OF market.ohlcv_daily
    FOR VALUES FROM ('2027-01-01') TO (MAXVALUE);

-- Access pattern 1: latest bar for a specific symbol+interval (most common)
CREATE INDEX idx_ohlcv_daily_sym_int_ts
    ON market.ohlcv_daily (symbol, interval, traded_at DESC);
-- Access pattern 2: all symbols on a specific date for a given interval (market scan)
CREATE INDEX idx_ohlcv_daily_int_ts
    ON market.ohlcv_daily (interval, traded_at DESC);
-- Access pattern 3: all symbols on a date for a given exchange (exchange-level analysis)
CREATE INDEX idx_ohlcv_daily_exch_int_ts
    ON market.ohlcv_daily (exchange, interval, traded_at DESC);

-- ──────────────────────────────────────────────────────────────────────────────
-- market.ohlcv_intraday
-- OHLCV bars for sub-daily intervals: 1m, 5m, 15m, 30m, 1H, 4h
-- Source : Quote.history(symbol, start, end, interval='1m'|'5m'|...'4h')
-- Upsert : ON CONFLICT (symbol, interval, traded_at) DO NOTHING
-- Partitioned RANGE by traded_at — MONTHLY (15.6M rows/month for 1m @ 1785 symbols)
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.ohlcv_intraday (
    symbol          VARCHAR(20)             NOT NULL,
    interval        public.interval_type    NOT NULL CHECK (interval IN ('1m','5m','15m','30m','1H','4h')),
    traded_at       TIMESTAMPTZ             NOT NULL,   -- bar open time Asia/Ho_Chi_Minh
    exchange        public.exchange_type    NOT NULL DEFAULT 'UNKNOWN',
    open            NUMERIC(18, 4)          NOT NULL,
    high            NUMERIC(18, 4)          NOT NULL,
    low             NUMERIC(18, 4)          NOT NULL,
    close           NUMERIC(18, 4)          NOT NULL,
    volume          BIGINT                  NOT NULL DEFAULT 0,
    value           NUMERIC(24, 0),
    data_source     VARCHAR(20)             NOT NULL,
    created_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, interval, traded_at)
) PARTITION BY RANGE (traded_at);

-- Monthly partitions — 2023
CREATE TABLE market.ohlcv_intraday_2023_01 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-01-01') TO ('2023-02-01');
CREATE TABLE market.ohlcv_intraday_2023_02 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-02-01') TO ('2023-03-01');
CREATE TABLE market.ohlcv_intraday_2023_03 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-03-01') TO ('2023-04-01');
CREATE TABLE market.ohlcv_intraday_2023_04 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-04-01') TO ('2023-05-01');
CREATE TABLE market.ohlcv_intraday_2023_05 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-05-01') TO ('2023-06-01');
CREATE TABLE market.ohlcv_intraday_2023_06 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-06-01') TO ('2023-07-01');
CREATE TABLE market.ohlcv_intraday_2023_07 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-07-01') TO ('2023-08-01');
CREATE TABLE market.ohlcv_intraday_2023_08 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-08-01') TO ('2023-09-01');
CREATE TABLE market.ohlcv_intraday_2023_09 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-09-01') TO ('2023-10-01');
CREATE TABLE market.ohlcv_intraday_2023_10 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-10-01') TO ('2023-11-01');
CREATE TABLE market.ohlcv_intraday_2023_11 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-11-01') TO ('2023-12-01');
CREATE TABLE market.ohlcv_intraday_2023_12 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2023-12-01') TO ('2024-01-01');
-- Monthly partitions — 2024
CREATE TABLE market.ohlcv_intraday_2024_01 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE market.ohlcv_intraday_2024_02 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE market.ohlcv_intraday_2024_03 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE market.ohlcv_intraday_2024_04 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE market.ohlcv_intraday_2024_05 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE market.ohlcv_intraday_2024_06 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE market.ohlcv_intraday_2024_07 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE market.ohlcv_intraday_2024_08 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE market.ohlcv_intraday_2024_09 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE market.ohlcv_intraday_2024_10 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE market.ohlcv_intraday_2024_11 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE market.ohlcv_intraday_2024_12 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
-- Monthly partitions — 2025
CREATE TABLE market.ohlcv_intraday_2025_01 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE market.ohlcv_intraday_2025_02 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE market.ohlcv_intraday_2025_03 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE market.ohlcv_intraday_2025_04 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE market.ohlcv_intraday_2025_05 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE market.ohlcv_intraday_2025_06 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
CREATE TABLE market.ohlcv_intraday_2025_07 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE market.ohlcv_intraday_2025_08 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE market.ohlcv_intraday_2025_09 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE market.ohlcv_intraday_2025_10 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE market.ohlcv_intraday_2025_11 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE market.ohlcv_intraday_2025_12 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
-- Monthly partitions — 2026 (add more as needed)
CREATE TABLE market.ohlcv_intraday_2026_01 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE market.ohlcv_intraday_2026_02 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE market.ohlcv_intraday_2026_03 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE market.ohlcv_intraday_2026_04 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE market.ohlcv_intraday_2026_05 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE market.ohlcv_intraday_2026_06 PARTITION OF market.ohlcv_intraday FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE market.ohlcv_intraday_default PARTITION OF market.ohlcv_intraday DEFAULT;

CREATE INDEX idx_ohlcv_intra_sym_int_ts
    ON market.ohlcv_intraday (symbol, interval, traded_at DESC);
CREATE INDEX idx_ohlcv_intra_int_ts
    ON market.ohlcv_intraday (interval, traded_at DESC);
CREATE INDEX idx_ohlcv_intra_exch_int_ts
    ON market.ohlcv_intraday (exchange, interval, traded_at DESC);

-- ──────────────────────────────────────────────────────────────────────────────
-- market.intraday_trade
-- Raw tick-by-tick matched orders.
-- Source : Quote.intraday(symbol, page_size, last_time)
-- Upsert : ON CONFLICT (symbol, traded_at, trade_id) DO NOTHING
--
-- Scale: ~3.6M rows/day for entire market → DAILY partitions.
-- IMPORTANT: Use pg_partman to auto-create and drop old daily partitions.
--   Install: CREATE EXTENSION pg_partman;
--   Setup  : SELECT partman.create_parent('market.intraday_trade', 'traded_at', 'native', 'daily');
--
-- The partitions below cover the current month as bootstrap examples only.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.intraday_trade (
    symbol          VARCHAR(20)         NOT NULL,
    traded_at       TIMESTAMPTZ         NOT NULL,
    price           NUMERIC(18, 4)      NOT NULL,
    volume          BIGINT              NOT NULL,
    match_type      public.match_side   NOT NULL DEFAULT 'unknown',
    trade_id        VARCHAR(80)         NOT NULL DEFAULT '',   -- source-native ID or composite
    price_change    NUMERIC(18, 4),
    accum_volume    BIGINT,
    accum_value     NUMERIC(24, 0),
    exchange        public.exchange_type NOT NULL DEFAULT 'UNKNOWN',
    data_source     VARCHAR(20)         NOT NULL,
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, traded_at, trade_id)
) PARTITION BY RANGE (traded_at);

-- Bootstrap partitions (March 2026) — pg_partman will manage the rest
CREATE TABLE market.intraday_trade_2026_03_01 PARTITION OF market.intraday_trade FOR VALUES FROM ('2026-03-01') TO ('2026-03-02');
CREATE TABLE market.intraday_trade_2026_03_02 PARTITION OF market.intraday_trade FOR VALUES FROM ('2026-03-02') TO ('2026-03-03');
CREATE TABLE market.intraday_trade_2026_03_03 PARTITION OF market.intraday_trade FOR VALUES FROM ('2026-03-03') TO ('2026-03-04');
CREATE TABLE market.intraday_trade_2026_03_04 PARTITION OF market.intraday_trade FOR VALUES FROM ('2026-03-04') TO ('2026-03-05');
CREATE TABLE market.intraday_trade_2026_03_05 PARTITION OF market.intraday_trade FOR VALUES FROM ('2026-03-05') TO ('2026-03-06');
CREATE TABLE market.intraday_trade_default PARTITION OF market.intraday_trade DEFAULT;

CREATE INDEX idx_intraday_sym_ts
    ON market.intraday_trade (symbol, traded_at DESC);
CREATE INDEX idx_intraday_exch_ts
    ON market.intraday_trade (exchange, traded_at DESC);
CREATE INDEX idx_intraday_match
    ON market.intraday_trade (symbol, match_type, traded_at DESC);

-- ──────────────────────────────────────────────────────────────────────────────
-- market.order_book_snapshot
-- Point-in-time bid/ask depth — 3 levels from Quote.price_depth(symbol)
-- Not partitioned (lower volume; retain last N snapshots per symbol via cron)
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.order_book_snapshot (
    id              BIGSERIAL       PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    snapshot_at     TIMESTAMPTZ     NOT NULL,
    bid1_price  NUMERIC(18,4), bid1_vol BIGINT,
    bid2_price  NUMERIC(18,4), bid2_vol BIGINT,
    bid3_price  NUMERIC(18,4), bid3_vol BIGINT,
    ask1_price  NUMERIC(18,4), ask1_vol BIGINT,
    ask2_price  NUMERIC(18,4), ask2_vol BIGINT,
    ask3_price  NUMERIC(18,4), ask3_vol BIGINT,
    data_source     VARCHAR(20)     NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, snapshot_at)
);

CREATE INDEX idx_orderbook_sym_ts ON market.order_book_snapshot (symbol, snapshot_at DESC);

-- ──────────────────────────────────────────────────────────────────────────────
-- market.index_ohlcv
-- OHLCV for market indices: VNINDEX, VN30, HNX30, UPCOMINDEX, VNMIDCAP, etc.
-- Separated from ohlcv_daily because indices have different fields
-- (no ceiling/floor/foreign flow) and belong to a different query domain.
-- Source : Quote.history(symbol='VNINDEX', interval='1D')
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.index_ohlcv (
    index_code      VARCHAR(20)             NOT NULL,
    interval        public.interval_type    NOT NULL,
    traded_at       TIMESTAMPTZ             NOT NULL,
    open            NUMERIC(18, 4)          NOT NULL,
    high            NUMERIC(18, 4)          NOT NULL,
    low             NUMERIC(18, 4)          NOT NULL,
    close           NUMERIC(18, 4)          NOT NULL,
    volume          BIGINT                  DEFAULT 0,
    value           NUMERIC(24, 0),
    -- Index-specific fields
    advances        INT,        -- number of stocks that went up
    declines        INT,        -- number of stocks that went down
    unchanged       INT,        -- number of stocks flat
    data_source     VARCHAR(20)             NOT NULL,
    created_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, interval, traded_at)
);

CREATE INDEX idx_idx_ohlcv_ts ON market.index_ohlcv (interval, traded_at DESC);

-- ──────────────────────────────────────────────────────────────────────────────
-- market.market_breadth
-- Daily market-wide statistics per exchange.
-- Source : aggregated from ohlcv_daily after each market close.
-- Used for: breadth analysis, cumulative advance-decline line, market health.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.market_breadth (
    trade_date      DATE                    NOT NULL,
    exchange        public.exchange_type    NOT NULL,
    -- Breadth counts
    advances        INT                     NOT NULL DEFAULT 0,
    declines        INT                     NOT NULL DEFAULT 0,
    unchanged       INT                     NOT NULL DEFAULT 0,
    total_trading   INT                     NOT NULL DEFAULT 0,
    -- Volume / value
    total_volume    BIGINT,
    total_value     NUMERIC(24, 0),
    -- Extremes
    new_highs_52w   INT                     DEFAULT 0,
    new_lows_52w    INT                     DEFAULT 0,
    -- Foreign net (exchange-level)
    foreign_net_vol BIGINT,
    foreign_net_val NUMERIC(24, 0),
    data_source     VARCHAR(20)             NOT NULL,
    created_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, exchange)
);

CREATE INDEX idx_breadth_exch_date ON market.market_breadth (exchange, trade_date DESC);

-- ──────────────────────────────────────────────────────────────────────────────
-- market.trading_halt
-- Tracks when a symbol was halted and when it resumed.
-- Source : exchange announcements / Listing.symbols_by_group('NG'|'DL'|'KH')
-- Used for: explaining gaps in ohlcv_daily / intraday_trade data.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.trading_halt (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    halt_date       DATE            NOT NULL,
    resume_date     DATE,
    halt_type       VARCHAR(20)     NOT NULL,   -- 'NG'=cảnh báo, 'DL'=kiểm soát, 'KH'=tạm dừng, 'HUY'=hủy niêm yết
    reason          TEXT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, halt_date, halt_type)
);

CREATE INDEX idx_halt_symbol ON market.trading_halt (symbol, halt_date DESC);
CREATE INDEX idx_halt_active  ON market.trading_halt (halt_date DESC) WHERE resume_date IS NULL;

-- ──────────────────────────────────────────────────────────────────────────────
-- market.price_adjustment
-- Corporate action adjustment factors for historical price correction.
-- Covers: stock splits, bonus shares, rights offerings, cash dividends.
-- Source : company.event (ex_date + value) + company.stock_split
--
-- adj_factor definition:
--   Adjusted price = raw price × adj_factor
--   Split 1:2  → adj_factor = 0.5  (price halved, volume doubled)
--   Dividend 1000 VND on price 50000 → adj_factor = (50000-1000)/50000 = 0.98
--
-- Usage: Apply cumulative product of adj_factor for all events AFTER the
--        target date to get fully-adjusted historical price.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE market.price_adjustment (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    ex_date         DATE            NOT NULL,
    action_type     VARCHAR(30)     NOT NULL,   -- 'split' | 'bonus' | 'rights' | 'cash_dividend'
    adj_factor      NUMERIC(16, 10) NOT NULL,   -- multiplicative factor for price
    vol_factor      NUMERIC(16, 10) NOT NULL DEFAULT 1.0, -- multiplicative factor for volume
    raw_value       NUMERIC(18, 4),             -- dividend per share, ratio, etc.
    description     TEXT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, ex_date, action_type)
);

CREATE INDEX idx_adj_symbol_date ON market.price_adjustment (symbol, ex_date DESC);


-- =============================================================================
--  SCHEMA: derivatives
--  Futures contract profiles and covered warrant profiles.
--  OHLCV price data for derivatives is stored in market.ohlcv_daily /
--  market.ohlcv_intraday (asset_type='futures'|'cw' in listing.symbol).
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS derivatives;

-- -----------------------------------------------------------------------------
-- derivatives.futures_profile
-- VN30 index futures: VN30F2503, VN30F2506, VN30F2509, VN30F2512, …
-- Source : Listing.all_future_indices()
-- -----------------------------------------------------------------------------
CREATE TABLE derivatives.futures_profile (
    contract_code       VARCHAR(20)             NOT NULL,
    underlying_symbol   VARCHAR(20)             NOT NULL DEFAULT 'VN30',
    exchange            public.exchange_type    NOT NULL DEFAULT 'HNX_DERIVATIVE',
    issue_date          DATE,
    first_trading_date  DATE,
    last_trading_date   DATE,
    maturity_date       DATE,
    contract_multiplier NUMERIC(12, 2)          DEFAULT 100000,  -- 100,000 VND per point
    tick_size           NUMERIC(12, 4)          DEFAULT 0.1,
    initial_margin      NUMERIC(18, 0),
    is_active           BOOLEAN                 NOT NULL DEFAULT TRUE,
    data_source         VARCHAR(20)             NOT NULL,
    fetched_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (contract_code)
);

CREATE INDEX idx_futures_active ON derivatives.futures_profile (is_active, last_trading_date);

-- -----------------------------------------------------------------------------
-- derivatives.warrant_profile
-- Covered warrants: CHPG2201, CMWG2202, CVHM2301, …
-- Source : Listing.all_covered_warrant()
-- -----------------------------------------------------------------------------
CREATE TABLE derivatives.warrant_profile (
    symbol              VARCHAR(20)             NOT NULL,
    issuer              TEXT                    NOT NULL,   -- 'SSI', 'VCI', 'MBS', …
    underlying_symbol   VARCHAR(20)             NOT NULL,
    exercise_price      NUMERIC(18, 4)          NOT NULL,
    exercise_ratio      NUMERIC(12, 6)          NOT NULL,   -- warrants needed per underlying share
    warrant_type        public.warrant_type     NOT NULL DEFAULT 'call',
    issue_date          DATE,
    first_trading_date  DATE,
    last_trading_date   DATE,
    maturity_date       DATE,
    listed_shares       BIGINT,
    exchange            public.exchange_type    NOT NULL DEFAULT 'HOSE',
    is_active           BOOLEAN                 NOT NULL DEFAULT TRUE,
    -- Derived / calculated fields (updated daily)
    underlying_price    NUMERIC(18, 4),
    break_even_point    NUMERIC(18, 4),
    intrinsic_value     NUMERIC(18, 4),
    data_source         VARCHAR(20)             NOT NULL,
    fetched_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol)
);

CREATE INDEX idx_warrant_underlying ON derivatives.warrant_profile (underlying_symbol, is_active);
CREATE INDEX idx_warrant_issuer     ON derivatives.warrant_profile (issuer, is_active);


-- =============================================================================
--  SCHEMA: company
--  Company reference data — profiles, shareholders, officers, events,
--  news, insider trades, capital history, stock splits
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS company;

-- -----------------------------------------------------------------------------
-- company.profile
-- Source : Company.overview()
-- Versioned by fetched_at — latest snapshot: DISTINCT ON (symbol) ORDER BY fetched_at DESC
-- raw_data JSONB stores source-specific fields not in the normalized columns.
-- -----------------------------------------------------------------------------
CREATE TABLE company.profile (
    id                  SERIAL              PRIMARY KEY,
    symbol              VARCHAR(20)         NOT NULL REFERENCES listing.symbol (symbol),
    company_name        TEXT,
    company_name_en     TEXT,
    exchange            public.exchange_type,
    icb_code            VARCHAR(20),
    founded_date        DATE,
    listing_date        DATE,
    charter_capital     NUMERIC(24, 0),     -- VND
    issued_shares       BIGINT,
    num_employees       INT,
    website             TEXT,
    tax_code            VARCHAR(20),
    address             TEXT,
    phone               TEXT,
    business_model      TEXT,
    description         TEXT,
    stock_type          VARCHAR(20),        -- 'stock', 'etf', 'cw', 'bond'
    raw_data            JSONB,
    data_source         VARCHAR(20)         NOT NULL,
    fetched_at          TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, data_source, fetched_at)
);

CREATE INDEX idx_co_profile_sym  ON company.profile (symbol, fetched_at DESC);
CREATE INDEX idx_co_profile_exch ON company.profile (exchange);
CREATE INDEX idx_co_raw          ON company.profile USING GIN (raw_data);

-- -----------------------------------------------------------------------------
-- company.shareholder
-- Source : Company.shareholders()
-- -----------------------------------------------------------------------------
CREATE TABLE company.shareholder (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    shareholder_name TEXT           NOT NULL,
    shares          BIGINT,
    ownership_pct   NUMERIC(10, 6),
    report_date     DATE,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, shareholder_name, report_date, data_source)
);

CREATE INDEX idx_shareholder_sym ON company.shareholder (symbol, report_date DESC);

-- -----------------------------------------------------------------------------
-- company.officer
-- Source : Company.officers(filter_by='working'|'resigned'|'all')
-- -----------------------------------------------------------------------------
CREATE TABLE company.officer (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    full_name       TEXT            NOT NULL,
    position_vn     TEXT,
    position_en     TEXT,
    from_date       DATE,
    to_date         DATE,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    owned_shares    BIGINT,
    ownership_pct   NUMERIC(10, 6),
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, full_name, from_date, data_source)
);

CREATE INDEX idx_officer_sym ON company.officer (symbol, is_active);

-- -----------------------------------------------------------------------------
-- company.subsidiary
-- Source : Company.subsidiaries() + Company.affiliate()
-- relation_type: 'cong_ty_con' (>50%) | 'cong_ty_lien_ket' (<=50%)
-- -----------------------------------------------------------------------------
CREATE TABLE company.subsidiary (
    id              SERIAL          PRIMARY KEY,
    parent_symbol   VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    sub_name        TEXT            NOT NULL,
    charter_capital NUMERIC(24, 0),
    ownership_pct   NUMERIC(10, 6),
    currency        VARCHAR(10)     DEFAULT 'VND',
    relation_type   VARCHAR(40),
    effective_date  DATE,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (parent_symbol, sub_name, data_source, fetched_at)
);

CREATE INDEX idx_subsidiary_parent ON company.subsidiary (parent_symbol);

-- -----------------------------------------------------------------------------
-- company.event
-- Source : Company.events()
-- event_type: 1=ĐHCĐ, 2=cổ tức, 3=phát hành, 4=GDNB, 5=khác
-- -----------------------------------------------------------------------------
CREATE TABLE company.event (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    event_type      SMALLINT        NOT NULL CHECK (event_type BETWEEN 1 AND 5),
    event_type_name VARCHAR(80),
    event_date      DATE,
    ex_date         DATE,
    record_date     DATE,
    payment_date    DATE,
    title           TEXT,
    description     TEXT,
    value           NUMERIC(18, 4),
    raw_data        JSONB,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, event_type, event_date, title, data_source)
);

CREATE INDEX idx_event_sym_date ON company.event (symbol, event_date DESC);
CREATE INDEX idx_event_type     ON company.event (event_type, event_date DESC);
CREATE INDEX idx_event_exdate   ON company.event (ex_date DESC) WHERE ex_date IS NOT NULL;

-- -----------------------------------------------------------------------------
-- company.news
-- Source : Company.news(page, page_size)
-- -----------------------------------------------------------------------------
CREATE TABLE company.news (
    id              BIGSERIAL       PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    news_id         VARCHAR(100),
    published_at    TIMESTAMPTZ,
    title           TEXT            NOT NULL,
    summary         TEXT,
    url             TEXT,
    source_name     TEXT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, news_id, data_source)
);

CREATE INDEX idx_news_sym_pub ON company.news (symbol, published_at DESC);

-- -----------------------------------------------------------------------------
-- company.insider_trade
-- Source : Company.insider_trading()
-- -----------------------------------------------------------------------------
CREATE TABLE company.insider_trade (
    id                  BIGSERIAL       PRIMARY KEY,
    symbol              VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    trader_name         TEXT,
    position            TEXT,
    transaction_date    DATE,
    method              VARCHAR(60),
    volume_registered   BIGINT,
    volume_executed     BIGINT,
    price               NUMERIC(18, 4),
    before_shares       BIGINT,
    after_shares        BIGINT,
    before_pct          NUMERIC(10, 6),
    after_pct           NUMERIC(10, 6),
    purpose             TEXT,
    raw_data            JSONB,
    data_source         VARCHAR(20)     NOT NULL,
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, trader_name, transaction_date, method, data_source)
);

CREATE INDEX idx_insider_sym_date ON company.insider_trade (symbol, transaction_date DESC);

-- -----------------------------------------------------------------------------
-- company.capital_history
-- Source : Company.capital_history()
-- -----------------------------------------------------------------------------
CREATE TABLE company.capital_history (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    event_date      DATE            NOT NULL,
    capital_vnd     NUMERIC(24, 0)  NOT NULL,
    note            TEXT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, event_date, data_source)
);

CREATE INDEX idx_capital_sym ON company.capital_history (symbol, event_date DESC);

-- -----------------------------------------------------------------------------
-- company.stock_split
-- Tracks all splits, bonus share issues, and consolidations.
-- Used as source data to populate market.price_adjustment.
-- split_ratio: new shares per old share (e.g., 2.0 = 1:2 split, 0.5 = 2:1 consolidation)
-- -----------------------------------------------------------------------------
CREATE TABLE company.stock_split (
    id              SERIAL          PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL REFERENCES listing.symbol (symbol),
    ex_date         DATE            NOT NULL,
    split_type      VARCHAR(20)     NOT NULL,   -- 'split' | 'bonus' | 'consolidation'
    split_ratio     NUMERIC(12, 6)  NOT NULL,   -- new_shares / old_shares
    description     TEXT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, ex_date, split_type)
);

CREATE INDEX idx_split_sym_date ON company.stock_split (symbol, ex_date DESC);


-- =============================================================================
--  SCHEMA: finance
--  Financial statements in EAV (Entity-Attribute-Value) format.
--  Rationale: KBS/VCI return 80-100 named line items per statement type.
--  EAV avoids 100-column wide tables and survives new line-items without
--  schema migrations. item_id is the normalized snake_case key.
--  Query: WHERE symbol='VNM' AND item_id='net_revenue' ORDER BY period_label DESC
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS finance;

-- -----------------------------------------------------------------------------
-- finance.income_statement
-- Source : Finance.income_statement(period='year'|'quarter', get_all=True)
-- -----------------------------------------------------------------------------
CREATE TABLE finance.income_statement (
    id              BIGSERIAL               PRIMARY KEY,
    symbol          VARCHAR(20)             NOT NULL,
    period_type     public.period_type      NOT NULL,
    period_label    VARCHAR(12)             NOT NULL,   -- '2024' | '2024-Q1'
    year            SMALLINT                NOT NULL,
    quarter         SMALLINT,               -- NULL for annual
    item_id         VARCHAR(120)            NOT NULL,   -- e.g. 'net_revenue', 'gross_profit'
    item_vn         TEXT,
    item_en         TEXT,
    value           NUMERIC(28, 4),
    unit            VARCHAR(20)             DEFAULT 'billion_vnd',
    row_order       SMALLINT,
    hierarchy_level SMALLINT,
    is_audited      BOOLEAN                 DEFAULT FALSE,
    data_source     VARCHAR(20)             NOT NULL,
    fetched_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, period_type, period_label, item_id, data_source)
);

CREATE INDEX idx_is_sym_period ON finance.income_statement (symbol, period_label DESC);
CREATE INDEX idx_is_item       ON finance.income_statement (item_id, period_label DESC);

-- -----------------------------------------------------------------------------
-- finance.balance_sheet
-- Source : Finance.balance_sheet(period='year'|'quarter', get_all=True)
-- -----------------------------------------------------------------------------
CREATE TABLE finance.balance_sheet (
    id              BIGSERIAL               PRIMARY KEY,
    symbol          VARCHAR(20)             NOT NULL,
    period_type     public.period_type      NOT NULL,
    period_label    VARCHAR(12)             NOT NULL,
    year            SMALLINT                NOT NULL,
    quarter         SMALLINT,
    item_id         VARCHAR(120)            NOT NULL,
    item_vn         TEXT,
    item_en         TEXT,
    value           NUMERIC(28, 4),
    unit            VARCHAR(20)             DEFAULT 'billion_vnd',
    row_order       SMALLINT,
    hierarchy_level SMALLINT,
    is_audited      BOOLEAN                 DEFAULT FALSE,
    data_source     VARCHAR(20)             NOT NULL,
    fetched_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, period_type, period_label, item_id, data_source)
);

CREATE INDEX idx_bs_sym_period ON finance.balance_sheet (symbol, period_label DESC);
CREATE INDEX idx_bs_item       ON finance.balance_sheet (item_id, period_label DESC);

-- -----------------------------------------------------------------------------
-- finance.cash_flow
-- Source : Finance.cash_flow(period='year'|'quarter', get_all=True)
-- -----------------------------------------------------------------------------
CREATE TABLE finance.cash_flow (
    id                  BIGSERIAL               PRIMARY KEY,
    symbol              VARCHAR(20)             NOT NULL,
    period_type         public.period_type      NOT NULL,
    period_label        VARCHAR(12)             NOT NULL,
    year                SMALLINT                NOT NULL,
    quarter             SMALLINT,
    cash_flow_method    VARCHAR(20)             DEFAULT 'indirect',  -- 'indirect' | 'direct'
    item_id             VARCHAR(120)            NOT NULL,
    item_vn             TEXT,
    item_en             TEXT,
    value               NUMERIC(28, 4),
    unit                VARCHAR(20)             DEFAULT 'billion_vnd',
    row_order           SMALLINT,
    hierarchy_level     SMALLINT,
    is_audited          BOOLEAN                 DEFAULT FALSE,
    data_source         VARCHAR(20)             NOT NULL,
    fetched_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, period_type, period_label, item_id, cash_flow_method, data_source)
);

CREATE INDEX idx_cf_sym_period ON finance.cash_flow (symbol, period_label DESC);

-- -----------------------------------------------------------------------------
-- finance.financial_ratio
-- Source : Finance.ratio(period='year'|'quarter')
-- ratio_group: 'valuation' | 'profitability' | 'growth' | 'liquidity' | 'asset_quality'
-- -----------------------------------------------------------------------------
CREATE TABLE finance.financial_ratio (
    id              BIGSERIAL               PRIMARY KEY,
    symbol          VARCHAR(20)             NOT NULL,
    period_type     public.period_type      NOT NULL,
    period_label    VARCHAR(12)             NOT NULL,
    year            SMALLINT                NOT NULL,
    quarter         SMALLINT,
    ratio_group     VARCHAR(60),
    item_id         VARCHAR(120)            NOT NULL,
    item_vn         TEXT,
    item_en         TEXT,
    value           NUMERIC(28, 8),
    unit            VARCHAR(20),
    row_order       SMALLINT,
    data_source     VARCHAR(20)             NOT NULL,
    fetched_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, period_type, period_label, item_id, data_source)
);

CREATE INDEX idx_ratio_sym_period ON finance.financial_ratio (symbol, period_label DESC);
CREATE INDEX idx_ratio_item       ON finance.financial_ratio (item_id, period_label DESC);


-- =============================================================================
--  SCHEMA: trading
--  Foreign flow, block/odd-lot trades, daily stats, price board snapshots
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS trading;

-- -----------------------------------------------------------------------------
-- trading.foreign_flow
-- Source : Trading.foreign_trade() — daily foreign buy/sell/net per symbol
-- -----------------------------------------------------------------------------
CREATE TABLE trading.foreign_flow (
    id              BIGSERIAL       PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    trade_date      DATE            NOT NULL,
    buy_volume      BIGINT,
    buy_value       NUMERIC(24, 0),
    sell_volume     BIGINT,
    sell_value      NUMERIC(24, 0),
    net_volume      BIGINT,
    net_value       NUMERIC(24, 0),
    room_remaining  BIGINT,         -- foreign ownership room left
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, trade_date, data_source)
);

CREATE INDEX idx_ff_sym_date ON trading.foreign_flow (symbol, trade_date DESC);
CREATE INDEX idx_ff_date     ON trading.foreign_flow (trade_date DESC);

-- -----------------------------------------------------------------------------
-- trading.block_trade  (giao dịch thỏa thuận)
-- Source : Trading.prop_trade() / Trading.put_through()
-- -----------------------------------------------------------------------------
CREATE TABLE trading.block_trade (
    id              BIGSERIAL       PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    traded_at       TIMESTAMPTZ     NOT NULL,
    price           NUMERIC(18, 4)  NOT NULL,
    volume          BIGINT          NOT NULL,
    value           NUMERIC(24, 0),
    buyer_code      VARCHAR(40),
    seller_code     VARCHAR(40),
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, traded_at, price, volume, data_source)
);

CREATE INDEX idx_bt_sym_date ON trading.block_trade (symbol, traded_at DESC);

-- -----------------------------------------------------------------------------
-- trading.odd_lot_trade  (giao dịch lô lẻ)
-- Source : Trading.odd_lot()
-- -----------------------------------------------------------------------------
CREATE TABLE trading.odd_lot_trade (
    id              BIGSERIAL           PRIMARY KEY,
    symbol          VARCHAR(20)         NOT NULL,
    traded_at       TIMESTAMPTZ         NOT NULL,
    price           NUMERIC(18, 4)      NOT NULL,
    volume          BIGINT              NOT NULL,
    match_type      public.match_side   DEFAULT 'unknown',
    data_source     VARCHAR(20)         NOT NULL,
    fetched_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, traded_at, price, volume, data_source)
);

CREATE INDEX idx_oddlot_sym_date ON trading.odd_lot_trade (symbol, traded_at DESC);

-- -----------------------------------------------------------------------------
-- trading.trading_stat
-- Source : Trading.trading_stats(start, end)
-- Daily aggregate: total volume, value, avg price, buy/sell breakdown
-- -----------------------------------------------------------------------------
CREATE TABLE trading.trading_stat (
    id              BIGSERIAL       PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    trade_date      DATE            NOT NULL,
    total_volume    BIGINT,
    total_value     NUMERIC(24, 0),
    avg_price       NUMERIC(18, 4),
    total_trades    INT,
    buy_volume      BIGINT,
    sell_volume     BIGINT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, trade_date, data_source)
);

CREATE INDEX idx_tstat_sym_date ON trading.trading_stat (symbol, trade_date DESC);

-- -----------------------------------------------------------------------------
-- trading.price_board_snapshot
-- Source : Trading.price_board(symbols_list)
-- Real-time full-market snapshot at a point in time
-- -----------------------------------------------------------------------------
CREATE TABLE trading.price_board_snapshot (
    id              BIGSERIAL       PRIMARY KEY,
    snapshot_at     TIMESTAMPTZ     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    ref_price       NUMERIC(18, 4),
    ceiling         NUMERIC(18, 4),
    floor           NUMERIC(18, 4),
    open            NUMERIC(18, 4),
    high            NUMERIC(18, 4),
    low             NUMERIC(18, 4),
    close           NUMERIC(18, 4),
    match_price     NUMERIC(18, 4),
    match_volume    BIGINT,
    total_volume    BIGINT,
    total_value     NUMERIC(24, 0),
    change          NUMERIC(18, 4),
    change_pct      NUMERIC(10, 6),
    foreign_buy     BIGINT,
    foreign_sell    BIGINT,
    raw_data        JSONB,
    data_source     VARCHAR(20)     NOT NULL,
    UNIQUE (symbol, snapshot_at, data_source)
);

CREATE INDEX idx_pbs_sym_ts ON trading.price_board_snapshot (symbol, snapshot_at DESC);
CREATE INDEX idx_pbs_ts     ON trading.price_board_snapshot (snapshot_at DESC);


-- =============================================================================
--  SCHEMA: index_data
--  Market index registry and constituent membership history
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS index_data;

-- -----------------------------------------------------------------------------
-- index_data.index_list
-- Source : Listing.all_indices(), Listing.indices_by_group()
-- -----------------------------------------------------------------------------
CREATE TABLE index_data.index_list (
    index_code      VARCHAR(20)             NOT NULL,
    index_name      TEXT,
    exchange        public.exchange_type,
    num_components  INT,
    description     TEXT,
    data_source     VARCHAR(20)             NOT NULL,
    fetched_at      TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code)
);

-- -----------------------------------------------------------------------------
-- index_data.index_constituent
-- Source : index-specific endpoints
-- Tracks historical component changes (effective/removal dates)
-- -----------------------------------------------------------------------------
CREATE TABLE index_data.index_constituent (
    index_code      VARCHAR(20)     NOT NULL REFERENCES index_data.index_list (index_code),
    symbol          VARCHAR(20)     NOT NULL,
    weight_pct      NUMERIC(10, 6),
    shares_listed   BIGINT,
    free_float_pct  NUMERIC(10, 6),
    effective_date  DATE            NOT NULL,
    removal_date    DATE,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, symbol, effective_date)
);

CREATE INDEX idx_ic_index  ON index_data.index_constituent (index_code, is_active);
CREATE INDEX idx_ic_symbol ON index_data.index_constituent (symbol);


-- =============================================================================
--  SCHEMA: fund
--  Mutual fund list, NAV history, portfolio holdings
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS fund;

-- -----------------------------------------------------------------------------
-- fund.fund
-- Source : Fund.listing()
-- -----------------------------------------------------------------------------
CREATE TABLE fund.fund (
    fund_id         INT             NOT NULL,   -- Fmarket internal integer ID
    short_name      VARCHAR(20)     NOT NULL,   -- ticker-like, e.g. 'SSISCA'
    fund_name       TEXT,
    fund_type       VARCHAR(20),               -- 'equity_fund' | 'bond_fund' | 'balanced_fund'
    issuer          TEXT,
    nav_per_unit    NUMERIC(18, 4),
    first_issue_at  DATE,
    nav_updated_at  DATE,
    nav_1m_pct      NUMERIC(10, 6),
    nav_3m_pct      NUMERIC(10, 6),
    nav_6m_pct      NUMERIC(10, 6),
    nav_1y_pct      NUMERIC(10, 6),
    nav_3y_pct      NUMERIC(10, 6),
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    data_source     VARCHAR(20)     NOT NULL DEFAULT 'fmarket',
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fund_id)
);

CREATE INDEX idx_fund_type ON fund.fund (fund_type, is_active);

-- -----------------------------------------------------------------------------
-- fund.nav_history
-- Source : Fund.nav_report(symbol) — daily NAV per unit
-- Partitioned RANGE by nav_date — annual (moderate volume)
-- -----------------------------------------------------------------------------
CREATE TABLE fund.nav_history (
    fund_id         INT             NOT NULL REFERENCES fund.fund (fund_id),
    nav_date        DATE            NOT NULL,
    nav_per_unit    NUMERIC(18, 4)  NOT NULL,
    data_source     VARCHAR(20)     NOT NULL DEFAULT 'fmarket',
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fund_id, nav_date)
) PARTITION BY RANGE (nav_date);

CREATE TABLE fund.nav_history_2022 PARTITION OF fund.nav_history FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE fund.nav_history_2023 PARTITION OF fund.nav_history FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE fund.nav_history_2024 PARTITION OF fund.nav_history FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE fund.nav_history_2025 PARTITION OF fund.nav_history FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE fund.nav_history_2026 PARTITION OF fund.nav_history FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE fund.nav_history_default PARTITION OF fund.nav_history DEFAULT;

CREATE INDEX idx_nav_fund_date ON fund.nav_history (fund_id, nav_date DESC);

-- -----------------------------------------------------------------------------
-- fund.top_holding / industry_holding / asset_holding
-- Source : Fund.top_holding() / Fund.industry_holding() / Fund.asset_holding()
-- -----------------------------------------------------------------------------
CREATE TABLE fund.top_holding (
    id              SERIAL          PRIMARY KEY,
    fund_id         INT             NOT NULL REFERENCES fund.fund (fund_id),
    stock_code      VARCHAR(20),
    industry        TEXT,
    net_asset_pct   NUMERIC(10, 6),
    asset_type      VARCHAR(20),    -- 'equity' | 'bond'
    reported_at     DATE,
    data_source     VARCHAR(20)     NOT NULL DEFAULT 'fmarket',
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (fund_id, stock_code, reported_at, data_source)
);

CREATE INDEX idx_th_fund ON fund.top_holding (fund_id, reported_at DESC);

CREATE TABLE fund.industry_holding (
    id              SERIAL          PRIMARY KEY,
    fund_id         INT             NOT NULL REFERENCES fund.fund (fund_id),
    industry        TEXT            NOT NULL,
    net_asset_pct   NUMERIC(10, 6),
    data_source     VARCHAR(20)     NOT NULL DEFAULT 'fmarket',
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (fund_id, industry, data_source, fetched_at)
);

CREATE TABLE fund.asset_holding (
    id              SERIAL          PRIMARY KEY,
    fund_id         INT             NOT NULL REFERENCES fund.fund (fund_id),
    asset_type      TEXT            NOT NULL,   -- 'equity' | 'bond' | 'cash_and_equivalents' | 'others'
    asset_pct       NUMERIC(10, 6),
    data_source     VARCHAR(20)     NOT NULL DEFAULT 'fmarket',
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (fund_id, asset_type, data_source, fetched_at)
);


-- =============================================================================
--  SCHEMA: macro
--  Macroeconomic indicators — exchange rates and economic time-series
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS macro;

-- -----------------------------------------------------------------------------
-- macro.exchange_rate
-- Source : Macro.exchange_rate() — VCB daily FX rates
-- -----------------------------------------------------------------------------
CREATE TABLE macro.exchange_rate (
    rate_date       DATE            NOT NULL,
    currency_code   VARCHAR(10)     NOT NULL,
    currency_name   TEXT,
    buy_cash        NUMERIC(18, 4),
    buy_transfer    NUMERIC(18, 4),
    sell            NUMERIC(18, 4),
    data_source     VARCHAR(20)     NOT NULL DEFAULT 'VCB',
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (rate_date, currency_code, data_source)
);

CREATE INDEX idx_er_date     ON macro.exchange_rate (rate_date DESC);
CREATE INDEX idx_er_currency ON macro.exchange_rate (currency_code, rate_date DESC);

-- -----------------------------------------------------------------------------
-- macro.economic_indicator
-- Generic EAV for: GDP, CPI, FDI, M2, REPO_RATE, industrial production,
--   retail sales, import/export, population/labor
-- Source : Macro.gdp() / Macro.cpi() / Macro.interest_rate() / etc.
-- indicator_code examples: 'GDP', 'CPI', 'FDI_REGISTERED', 'M2', 'REPO_RATE',
--   'IIP', 'RETAIL_SALES', 'EXPORT_VALUE', 'IMPORT_VALUE', 'POPULATION'
-- -----------------------------------------------------------------------------
CREATE TABLE macro.economic_indicator (
    id              BIGSERIAL       PRIMARY KEY,
    indicator_code  VARCHAR(40)     NOT NULL,
    indicator_name  TEXT,
    period_label    VARCHAR(20)     NOT NULL,   -- '2024' | '2024-Q1' | '2024-01'
    period_start    DATE,
    period_end      DATE,
    value           NUMERIC(28, 8),
    unit            VARCHAR(40),               -- '%' | 'billion_usd' | 'trillion_vnd' | …
    yoy_change_pct  NUMERIC(12, 6),
    data_source     VARCHAR(30)     NOT NULL,
    raw_data        JSONB,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (indicator_code, period_label, data_source)
);

CREATE INDEX idx_ei_code_period ON macro.economic_indicator (indicator_code, period_label DESC);
CREATE INDEX idx_ei_period_end  ON macro.economic_indicator (period_end DESC);


-- =============================================================================
--  SCHEMA: commodity
--  Gold, gasoline/oil, steel, fertilizer prices
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS commodity;

-- -----------------------------------------------------------------------------
-- commodity.gold_price
-- Source : CommodityPrice.gold_vn() / CommodityPrice.gold_global()
-- -----------------------------------------------------------------------------
CREATE TABLE commodity.gold_price (
    id              BIGSERIAL       PRIMARY KEY,
    price_date      DATE            NOT NULL,
    provider        VARCHAR(20)     NOT NULL,   -- 'SJC' | 'BTMC' | 'GLOBAL'
    gold_type       VARCHAR(80),               -- 'Vang mien SJC' | 'Vang nhan 9999' | …
    karat           VARCHAR(10),
    gold_content    NUMERIC(10, 4),
    buy_price       NUMERIC(18, 2),
    sell_price      NUMERIC(18, 2),
    world_price     NUMERIC(18, 4),            -- USD reference
    currency        VARCHAR(10)     DEFAULT 'VND',
    branch          TEXT,
    data_source     VARCHAR(20)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (price_date, provider, gold_type, branch, data_source)
);

CREATE INDEX idx_gold_date ON commodity.gold_price (price_date DESC, provider);

-- -----------------------------------------------------------------------------
-- commodity.commodity_price
-- Source : CommodityPrice.gas_vn() / .steel_d10() / .fertilizer_ure() / etc.
-- commodity_code examples: 'RON95', 'RON92', 'DO_0_05S', 'STEEL_D10',
--   'IRON_ORE', 'STEEL_HRC', 'UREA', 'SOYBEAN', 'CORN', 'SUGAR'
-- -----------------------------------------------------------------------------
CREATE TABLE commodity.commodity_price (
    id              BIGSERIAL       PRIMARY KEY,
    price_date      DATE            NOT NULL,
    commodity_code  VARCHAR(40)     NOT NULL,
    commodity_name  TEXT,
    price           NUMERIC(18, 4)  NOT NULL,
    unit            VARCHAR(30)     DEFAULT 'VND/liter',
    region          VARCHAR(40),               -- 'HCM' | 'HN' | 'national' | 'global'
    data_source     VARCHAR(30)     NOT NULL,
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (price_date, commodity_code, region, data_source)
);

CREATE INDEX idx_commodity_date ON commodity.commodity_price (commodity_code, price_date DESC);


-- =============================================================================
--  SCHEMA: etl
--  Pipeline control: collection tiers, per-symbol config, job registry,
--  execution logs, data freshness tracker, schedule overrides, global state
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS etl;

CREATE TYPE etl.run_status AS ENUM (
    'pending', 'running', 'success', 'partial', 'failed', 'skipped', 'timeout'
);

-- ──────────────────────────────────────────────────────────────────────────────
-- etl.collection_tier
-- Defines what data is collected for each tier of symbols.
-- Tier 1 = liquid (VN30): everything at high frequency
-- Tier 2 = mid-cap (VN100 ex-VN30): daily + 5m bars + core fundamentals
-- Tier 3 = small-cap (rest of HOSE + HNX): daily OHLCV + quarterly financials
-- Tier 4 = UPCOM: daily OHLCV only
-- Tier 5 = derivatives (futures + CW): daily + intraday based on liquidity
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE etl.collection_tier (
    tier                    SMALLINT    NOT NULL,
    tier_name               VARCHAR(30) NOT NULL,
    collect_ohlcv_daily     BOOLEAN     NOT NULL DEFAULT TRUE,
    collect_ohlcv_intraday  BOOLEAN     NOT NULL DEFAULT FALSE,
    intraday_intervals      TEXT[],     -- e.g. ARRAY['1m','5m','15m']
    collect_ticks           BOOLEAN     NOT NULL DEFAULT FALSE,
    collect_order_book      BOOLEAN     NOT NULL DEFAULT FALSE,
    collect_company         BOOLEAN     NOT NULL DEFAULT FALSE,
    collect_finance         BOOLEAN     NOT NULL DEFAULT FALSE,
    collect_trading_flow    BOOLEAN     NOT NULL DEFAULT FALSE,
    bootstrap_days          INT         NOT NULL DEFAULT 365,
    description             TEXT,
    PRIMARY KEY (tier)
);

INSERT INTO etl.collection_tier VALUES
-- tier  name            ohlcv_daily  intraday  intervals                ticks   orderbook  company finance  flow  bootstrap  desc
(1, 'liquid_vn30',       TRUE, TRUE,  ARRAY['1m','5m','15m','1H'],TRUE,  TRUE,   TRUE,  TRUE,  TRUE,  1095, 'VN30 + most liquid stocks'),
(2, 'mid_cap',           TRUE, TRUE,  ARRAY['5m','15m'],          FALSE, FALSE,  TRUE,  TRUE,  TRUE,  1095, 'VN100 excluding VN30'),
(3, 'small_cap_listed',  TRUE, FALSE, NULL,                        FALSE, FALSE,  TRUE,  TRUE,  TRUE,   730, 'Remaining HOSE + HNX'),
(4, 'upcom',             TRUE, FALSE, NULL,                        FALSE, FALSE,  FALSE, FALSE, FALSE,  365, 'UPCOM symbols'),
(5, 'derivatives',       TRUE, TRUE,  ARRAY['1m','5m'],            TRUE,  FALSE,  FALSE, FALSE, FALSE,  365, 'Futures and covered warrants');

-- ──────────────────────────────────────────────────────────────────────────────
-- etl.symbol_collection_config
-- Per-symbol collection settings. Replaces the simple etl.watchlist.
-- Seeded automatically when listing.symbol is refreshed.
-- Individual columns can override the tier defaults.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE etl.symbol_collection_config (
    symbol                  VARCHAR(20)     NOT NULL,
    tier                    SMALLINT        NOT NULL REFERENCES etl.collection_tier (tier),
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    -- Per-symbol overrides (NULL = inherit from tier)
    override_ohlcv_daily    BOOLEAN,
    override_ohlcv_intraday BOOLEAN,
    override_ticks          BOOLEAN,
    override_company        BOOLEAN,
    override_finance        BOOLEAN,
    override_trading_flow   BOOLEAN,
    priority                SMALLINT        NOT NULL DEFAULT 5,     -- 1=highest, 10=lowest
    added_at                TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    note                    TEXT,
    PRIMARY KEY (symbol)
);

CREATE INDEX idx_scc_tier_active ON etl.symbol_collection_config (tier, is_active, priority);

-- Seed initial watchlist from settings.py into tier 1
INSERT INTO etl.symbol_collection_config (symbol, tier, priority) VALUES
    ('VNM', 1, 1), ('FPT', 1, 1), ('VIC', 1, 1), ('VHM', 1, 1), ('TCB', 1, 1),
    ('VCB', 1, 1), ('MWG', 1, 2), ('HPG', 1, 2), ('MSN', 1, 2), ('VRE', 1, 2),
    ('SSI', 1, 3), ('HDB', 1, 3), ('VPB', 1, 3), ('ACB', 1, 3), ('BID', 1, 3);

-- ──────────────────────────────────────────────────────────────────────────────
-- etl.job_definition
-- Registry of all ETL jobs. Correlates with APScheduler via job_id string.
-- APScheduler manages trigger state; this table manages business metadata.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE etl.job_definition (
    job_id              VARCHAR(80)     NOT NULL,
    job_name            TEXT            NOT NULL,
    job_category        VARCHAR(40),             -- 'market' | 'company' | 'finance' | ...
    job_type            VARCHAR(20)     NOT NULL DEFAULT 'scheduled',  -- 'scheduled' | 'bootstrap' | 'manual'
    -- Schedule (mirrors APScheduler trigger params)
    schedule_type       VARCHAR(20),             -- 'cron' | 'interval' | 'date'
    cron_expression     VARCHAR(80),             -- e.g. '15 16 * * MON-FRI'
    interval_seconds    INT,
    -- Behavior
    timeout_seconds     INT             DEFAULT 300,
    max_retries         SMALLINT        DEFAULT 3,
    retry_delay_sec     INT             DEFAULT 60,
    -- Scope
    applies_to          VARCHAR(20)     DEFAULT 'tier',   -- 'tier' | 'all_symbols' | 'global'
    target_tier         SMALLINT,                         -- NULL = all tiers
    target_interval     VARCHAR(10),                      -- for OHLCV jobs
    target_source       VARCHAR(20),                      -- 'KBS' | 'VCI' | 'VND' | ...
    config              JSONB,
    is_enabled          BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id)
);

INSERT INTO etl.job_definition
    (job_id, job_name, job_category, job_type, schedule_type, cron_expression, applies_to, target_tier, target_interval, target_source)
VALUES
    -- ── Bootstrap jobs (run once on first start) ──────────────────────────
    ('bootstrap_ohlcv_daily_all',
     'Bootstrap daily OHLCV for all symbols',
     'market', 'bootstrap', NULL, NULL, 'all_symbols', NULL, '1D', 'KBS'),

    ('bootstrap_ohlcv_intraday_t1',
     'Bootstrap intraday bars for tier-1 symbols',
     'market', 'bootstrap', NULL, NULL, 'tier', 1, '1m', 'KBS'),

    ('bootstrap_ohlcv_intraday_t2',
     'Bootstrap intraday bars for tier-2 symbols',
     'market', 'bootstrap', NULL, NULL, 'tier', 2, '5m', 'KBS'),

    ('bootstrap_company_all',
     'Bootstrap company data for all listed symbols',
     'company', 'bootstrap', NULL, NULL, 'all_symbols', NULL, NULL, 'VCI'),

    ('bootstrap_finance_all',
     'Bootstrap financial statements for all symbols',
     'finance', 'bootstrap', NULL, NULL, 'all_symbols', NULL, NULL, 'KBS'),

    -- ── Daily market jobs (weekdays after close) ──────────────────────────
    ('fetch_ohlcv_daily_all',
     'Fetch daily OHLCV for all active symbols after close',
     'market', 'scheduled', 'cron', '15 16 * * MON-FRI', 'all_symbols', NULL, '1D', 'KBS'),

    ('fetch_intraday_bars_t1',
     'Fetch intraday bars 1m/5m/15m for tier-1 (real-time during session)',
     'market', 'scheduled', 'cron', '*/5 9-15 * * MON-FRI', 'tier', 1, '1m', 'KBS'),

    ('fetch_intraday_bars_t2',
     'Fetch intraday bars 5m/15m for tier-2 (every 15 min)',
     'market', 'scheduled', 'cron', '*/15 9-15 * * MON-FRI', 'tier', 2, '5m', 'KBS'),

    ('fetch_tick_trades_t1',
     'Fetch raw tick trades end-of-day for tier-1',
     'market', 'scheduled', 'cron', '35 15 * * MON-FRI', 'tier', 1, NULL, 'KBS'),

    ('fetch_index_ohlcv',
     'Fetch OHLCV for VNINDEX, VN30, HNX30, UPCOMINDEX',
     'market', 'scheduled', 'cron', '20 16 * * MON-FRI', 'global', NULL, '1D', 'VCI'),

    ('fetch_market_breadth',
     'Aggregate and store daily market breadth per exchange',
     'market', 'scheduled', 'cron', '30 16 * * MON-FRI', 'global', NULL, NULL, NULL),

    ('fetch_foreign_flow_all',
     'Fetch daily foreign buy/sell/net for all symbols',
     'trading', 'scheduled', 'cron', '0 17 * * MON-FRI', 'all_symbols', NULL, NULL, 'VCI'),

    ('fetch_price_board_snapshot',
     'Capture full-market price board snapshot during session',
     'trading', 'scheduled', 'cron', '*/10 9-15 * * MON-FRI', 'global', NULL, NULL, 'VCI'),

    -- ── Derivatives ────────────────────────────────────────────────────────
    ('fetch_derivatives_ohlcv',
     'Fetch daily OHLCV for all active futures contracts',
     'market', 'scheduled', 'cron', '15 16 * * MON-FRI', 'tier', 5, '1D', 'KBS'),

    ('refresh_warrant_profiles',
     'Refresh covered warrant profiles and pricing',
     'derivatives', 'scheduled', 'cron', '0 8 * * MON-FRI', 'global', NULL, NULL, 'KBS'),

    -- ── Company data (weekly) ──────────────────────────────────────────────
    ('fetch_company_profile_all',
     'Refresh company profiles for all listed symbols',
     'company', 'scheduled', 'cron', '0 8 * * MON', 'all_symbols', NULL, NULL, 'VCI'),

    ('fetch_insider_trades',
     'Fetch insider trading disclosures',
     'company', 'scheduled', 'cron', '30 8 * * MON', 'all_symbols', NULL, NULL, 'VCI'),

    ('detect_corporate_actions',
     'Detect new splits/dividends and populate price_adjustment',
     'company', 'scheduled', 'cron', '0 9 * * MON-FRI', 'all_symbols', NULL, NULL, 'VCI'),

    -- ── Listing / indices (weekly) ─────────────────────────────────────────
    ('refresh_symbol_listing',
     'Refresh full symbol list from all exchanges',
     'listing', 'scheduled', 'cron', '0 7 * * MON', 'global', NULL, NULL, 'VCI'),

    ('refresh_index_constituents',
     'Refresh index constituent lists (VN30, HNX30, etc.)',
     'listing', 'scheduled', 'cron', '30 7 * * MON', 'global', NULL, NULL, 'VCI'),

    ('refresh_symbol_groups',
     'Refresh symbol group memberships (VN100, VNMIDCAP, etc.)',
     'listing', 'scheduled', 'cron', '45 7 * * MON', 'global', NULL, NULL, 'VCI'),

    ('update_trading_calendar',
     'Update trading calendar with upcoming holidays',
     'listing', 'scheduled', 'cron', '0 6 1 1,7 *', 'global', NULL, NULL, NULL),

    -- ── Financial statements (monthly) ────────────────────────────────────
    ('fetch_financial_statements_all',
     'Fetch quarterly financial statements for all symbols',
     'finance', 'scheduled', 'cron', '0 9 1 * *', 'all_symbols', NULL, NULL, 'KBS'),

    -- ── Macro + Commodity (weekly / daily) ────────────────────────────────
    ('fetch_macro_indicators',
     'Fetch GDP, CPI, FDI, M2, interest rate, exchange rate data',
     'macro', 'scheduled', 'cron', '0 10 * * MON', 'global', NULL, NULL, 'MBK'),

    ('fetch_exchange_rates',
     'Fetch VCB daily FX rates',
     'macro', 'scheduled', 'cron', '30 8 * * MON-FRI', 'global', NULL, NULL, 'VCB'),

    ('fetch_commodity_prices',
     'Fetch gold, gasoline, steel, fertilizer prices',
     'commodity', 'scheduled', 'cron', '0 8 * * MON-FRI', 'global', NULL, NULL, 'SPL'),

    -- ── Fund data (daily) ──────────────────────────────────────────────────
    ('fetch_fund_nav',
     'Fetch daily NAV for all active mutual funds',
     'fund', 'scheduled', 'cron', '0 20 * * MON-FRI', 'global', NULL, NULL, 'fmarket'),

    ('refresh_fund_holdings',
     'Refresh fund top/industry/asset holdings (monthly rebalancing)',
     'fund', 'scheduled', 'cron', '0 21 1 * *', 'global', NULL, NULL, 'fmarket');

-- ──────────────────────────────────────────────────────────────────────────────
-- etl.job_run
-- Execution log — one row per job attempt.
-- status flow: pending → running → success | partial | failed | timeout | skipped
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE etl.job_run (
    id                  BIGSERIAL           PRIMARY KEY,
    job_id              VARCHAR(80)         NOT NULL REFERENCES etl.job_definition (job_id),
    run_at              TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    duration_ms         INT,
    status              etl.run_status      NOT NULL DEFAULT 'pending',
    -- Run scope
    symbol              VARCHAR(20),        -- NULL = entire tier or global
    target_tier         SMALLINT,
    target_interval     VARCHAR(10),
    date_from           DATE,
    date_to             DATE,
    -- Outcomes
    rows_fetched        INT                 DEFAULT 0,
    rows_inserted       INT                 DEFAULT 0,
    rows_updated        INT                 DEFAULT 0,
    rows_skipped        INT                 DEFAULT 0,
    error_message       TEXT,
    error_traceback     TEXT,
    -- APScheduler correlation
    scheduler_job_id    VARCHAR(100),
    host_name           VARCHAR(100),
    pid                 INT
);

CREATE INDEX idx_jobrun_job     ON etl.job_run (job_id, run_at DESC);
CREATE INDEX idx_jobrun_status  ON etl.job_run (status, run_at DESC);
CREATE INDEX idx_jobrun_symbol  ON etl.job_run (symbol, job_id, run_at DESC) WHERE symbol IS NOT NULL;

-- ──────────────────────────────────────────────────────────────────────────────
-- etl.data_freshness
-- Per-(symbol, data_type) freshness tracker.
-- Used by bootstrap logic: on startup, scan for is_bootstrapped=FALSE rows
-- and fetch history back to (NOW() - bootstrap_days from tier config).
-- On container restart, already-bootstrapped data is NOT re-fetched.
-- Use '_global_' as symbol for non-symbol data (macro, fund, commodity, listing).
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE etl.data_freshness (
    symbol                  VARCHAR(20)     NOT NULL,
    data_type               VARCHAR(60)     NOT NULL,   -- 'ohlcv_daily.1D' | 'ohlcv_intraday.1m' | 'ticks' | 'company.profile' | ...
    target_table            VARCHAR(80)     NOT NULL,   -- 'market.ohlcv_daily', etc.
    data_source             VARCHAR(20),
    -- Coverage
    earliest_date           DATE,
    latest_date             DATE,
    row_count               BIGINT          DEFAULT 0,
    -- Bootstrap state
    is_bootstrapped         BOOLEAN         NOT NULL DEFAULT FALSE,
    bootstrap_started_at    TIMESTAMPTZ,
    bootstrap_completed_at  TIMESTAMPTZ,
    -- Freshness
    last_successful_fetch   TIMESTAMPTZ,
    last_attempted_fetch    TIMESTAMPTZ,
    consecutive_failures    SMALLINT        DEFAULT 0,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, data_type, data_source)
);

CREATE INDEX idx_freshness_stale ON etl.data_freshness (latest_date ASC)
    WHERE is_bootstrapped = TRUE;
CREATE INDEX idx_freshness_sym   ON etl.data_freshness (symbol, data_type);

-- ──────────────────────────────────────────────────────────────────────────────
-- etl.schedule_override
-- Temporarily pause, reschedule, or force-run a job without code changes.
-- Checked by the scheduler decorator before each job execution.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE etl.schedule_override (
    id              SERIAL          PRIMARY KEY,
    job_id          VARCHAR(80)     NOT NULL REFERENCES etl.job_definition (job_id),
    override_type   VARCHAR(20)     NOT NULL,   -- 'pause' | 'reschedule' | 'force_run'
    reason          TEXT,
    effective_from  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    effective_until TIMESTAMPTZ,
    new_cron_expr   VARCHAR(80),
    created_by      VARCHAR(60)     DEFAULT 'system',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────────────────────
-- etl.pipeline_state
-- Global key-value flags for pipeline coordination.
-- One row per named flag; avoids a generic config table sprawl.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE etl.pipeline_state (
    key         VARCHAR(80)     PRIMARY KEY,
    value_text  TEXT,
    value_int   BIGINT,
    value_bool  BOOLEAN,
    value_ts    TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

INSERT INTO etl.pipeline_state (key, value_bool, updated_at) VALUES
    ('bootstrap_completed',         FALSE, NOW()),
    ('scheduler_running',           FALSE, NOW()),
    ('listing_last_synced',         NULL,  NOW()),
    ('calendar_last_synced',        NULL,  NOW());
