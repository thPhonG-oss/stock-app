# Tài Liệu Data Pipeline — Stock App

> **Ngôn ngữ:** Tiếng Việt
> **Cập nhật:** 2026-03-15
> **Database:** PostgreSQL 16 | **Framework:** APScheduler + SQLAlchemy + vnstock

---

## Mục Lục

1. [Tổng Quan Hệ Thống](#1-tổng-quan-hệ-thống)
2. [Kiến Trúc Pipeline — Luồng ETL](#2-kiến-trúc-pipeline--luồng-etl)
3. [Cách Scheduler Hoạt Động](#3-cách-scheduler-hoạt-động)
4. [Thiết Kế Cơ Sở Dữ Liệu](#4-thiết-kế-cơ-sở-dữ-liệu)
   - [ENUM Types Dùng Chung](#41-enum-types-dùng-chung)
   - [Schema: listing](#42-schema-listing)
   - [Schema: market](#43-schema-market)
   - [Schema: derivatives](#44-schema-derivatives)
   - [Schema: company](#45-schema-company)
   - [Schema: finance](#46-schema-finance)
   - [Schema: trading](#47-schema-trading)
   - [Schema: index_data](#48-schema-index_data)
   - [Schema: fund](#49-schema-fund)
   - [Schema: macro](#410-schema-macro)
   - [Schema: commodity](#411-schema-commodity)
   - [Schema: etl](#412-schema-etl)
5. [Các Extractor — Tầng Trích Xuất Dữ Liệu](#5-các-extractor--tầng-trích-xuất-dữ-liệu)
6. [Các Transformer — Tầng Chuyển Đổi Dữ Liệu](#6-các-transformer--tầng-chuyển-đổi-dữ-liệu)
7. [Các Loader & Repository — Tầng Lưu Trữ](#7-các-loader--repository--tầng-lưu-trữ)
8. [Các Jobs — Chi Tiết Từng Công Việc](#8-các-jobs--chi-tiết-từng-công-việc)
9. [Dữ Liệu Thu Thập & Scale](#9-dữ-liệu-thu-thập--scale)
10. [Công Cụ Backfill — Chạy Thủ Công](#10-công-cụ-backfill--chạy-thủ-công)

---

## 1. Tổng Quan Hệ Thống

Data pipeline này là hệ thống thu thập và lưu trữ dữ liệu thị trường chứng khoán Việt Nam tự động, bao gồm:

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Nguồn dữ liệu | **vnstock** (VCI source) | Cung cấp API lấy dữ liệu từ sàn HOSE, HNX, UPCOM |
| Lịch chạy | **APScheduler** (BlockingScheduler) | Quản lý thời gian chạy các jobs |
| Cơ sở dữ liệu | **PostgreSQL 16** | Lưu trữ toàn bộ dữ liệu |
| ORM / Query | **SQLAlchemy 2.x** + **psycopg2** | Kết nối và thực thi SQL |
| Logging | **Loguru** | Ghi log ra file và console |
| Cấu hình | **pydantic-settings** | Đọc cấu hình từ file `.env` |
| Cache/Queue | **Redis 7** | Hàng đợi (dự phòng cho tương lai) |

**Phạm vi thu thập:**
- ~1.785 mã chứng khoán: HOSE (~400) + HNX (~300) + UPCOM (~700) + Phái sinh (~30) + CW (~120) + ETF (~35) + Trái phiếu (~200)
- Dữ liệu giá OHLCV ngày, intraday, tick-by-tick
- Thông tin công ty, báo cáo tài chính, giao dịch khối ngoại
- Dữ liệu vĩ mô, quỹ đầu tư, hàng hóa

---

## 2. Kiến Trúc Pipeline — Luồng ETL

Pipeline theo mô hình **ETL (Extract → Transform → Load)** 3 tầng:

```
┌─────────────────────────────────────────────────────────────────┐
│                         scheduler.py                            │
│              APScheduler (BlockingScheduler)                    │
│         Cron jobs chạy tự động theo lịch định sẵn              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ gọi job functions
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      jobs/*.py                                  │
│   listing_jobs / market_jobs / company_jobs /                   │
│   finance_jobs / trading_jobs                                   │
│   → Điều phối toàn bộ luồng ETL cho 1 loại dữ liệu             │
└──────┬──────────────────────────────────────────────────────────┘
       │
       ▼ EXTRACT                    ▼ TRANSFORM              ▼ LOAD
┌──────────────┐           ┌──────────────────┐     ┌────────────────┐
│ extractors/  │           │  transformers/   │     │   loaders/     │
│              │──DataFrame│                  │─────│                │
│ Gọi vnstock  │──────────▶│ Chuẩn hóa data,  │list │ Upsert vào DB  │
│ API, trả về  │           │ mapping cột,     │[dict│ qua Repository │
│ pandas DF    │           │ ép kiểu dữ liệu  │]   ─▶                │
└──────────────┘           └──────────────────┘     └────────┬───────┘
                                                             │
                                                             ▼
                                              ┌──────────────────────┐
                                              │  db/repositories/    │
                                              │                      │
                                              │  Thực thi SQL upsert │
                                              │  ON CONFLICT DO      │
                                              │  UPDATE / NOTHING    │
                                              └──────────┬───────────┘
                                                         │
                                                         ▼
                                              ┌──────────────────────┐
                                              │   PostgreSQL 16      │
                                              │   Database: stockapp │
                                              │   11 schemas         │
                                              │   50+ tables         │
                                              └──────────────────────┘
```

### Vòng đời 1 lần chạy job (ví dụ: OHLCV daily)

```
job_fetch_ohlcv_daily()
  │
  ├─ 1. Lấy danh sách symbols từ listing.symbol trong DB
  │
  ├─ 2. Với mỗi symbol (theo batch, 50 symbols/batch):
  │     ├─ Kiểm tra ngày cuối cùng đã có trong market.ohlcv_daily
  │     │    → Nếu có: fetch từ ngày đó + 1 (incremental)
  │     │    → Nếu chưa: fetch từ 3 năm trước (bootstrap)
  │     │
  │     ├─ [EXTRACT] MarketExtractor.extract_ohlcv_daily(symbol, start, end)
  │     │    → Gọi vnstock Quote.history() → pandas DataFrame
  │     │
  │     ├─ [TRANSFORM] MarketTransformer.transform_ohlcv_daily(df, symbol, exchange)
  │     │    → Chuẩn hóa cột, ép kiểu float/int, loại bỏ null
  │     │    → Trả về list[dict] tương thích với schema DB
  │     │
  │     └─ [LOAD] MarketLoader.load_ohlcv_daily(records)
  │          → MarketRepository.upsert_ohlcv_daily()
  │          → INSERT ... ON CONFLICT (symbol, interval, traded_at) DO NOTHING
  │
  └─ 3. Log kết quả: tổng rows loaded, số errors
```

---

## 3. Cách Scheduler Hoạt Động

File điều phối chính: `scheduler.py` → entry point: `main.py`

### Chuỗi khởi động (Bootstrap Sequence)

```
python main.py
    │
    ├─ 1. setup_logging()       — Cấu hình Loguru ghi vào logs/pipeline.log
    │
    ├─ 2. bootstrap()
    │     ├─ init_schema()      — Đọc db/scripts/schema.sql và chạy DDL
    │     │                       (bỏ qua nếu listing.symbol đã tồn tại)
    │     └─ job_sync_listing() — Đồng bộ toàn bộ mã CK + ngành ICB ngay khi khởi động
    │
    └─ 3. create_scheduler()    — Đăng ký 5 cron jobs
         scheduler.start()      — Chạy blocking, lắng nghe theo lịch
```

### 5 Jobs Đã Đăng Ký trong Scheduler

| Job ID | Hàm | Lịch chạy | Mô tả |
|---|---|---|---|
| `refresh_symbol_listing` | `job_sync_listing` | Thứ 2, 7:00 AM | Đồng bộ danh sách mã CK + ICB |
| `fetch_ohlcv_daily_all` | `job_fetch_ohlcv_daily` | Thứ 2-6, 17:30 | Lấy giá OHLCV daily sau khi sàn đóng |
| `fetch_company_profile_all` | `job_fetch_company_profiles` | Thứ 2, 8:00 AM | Cập nhật thông tin công ty hàng tuần |
| `fetch_financial_statements_all` | `job_fetch_financial_statements` | Ngày 1 mỗi tháng, 9:00 AM | Lấy báo cáo tài chính hàng quý |
| `fetch_foreign_flow_all` | `job_fetch_foreign_flow` | Thứ 2-6, 17:45 | Lấy giao dịch khối ngoại |

### Cấu hình Scheduler

```python
BlockingScheduler(
    timezone="Asia/Ho_Chi_Minh",
    coalesce=True,           # Nhiều lần miss → gộp thành 1 lần chạy
    max_instances=1,         # Không chạy song song 2 instance cùng job
    misfire_grace_time=3600, # Cho phép trễ tối đa 1 giờ
)
```

---

## 4. Thiết Kế Cơ Sở Dữ Liệu

Database: `stockapp` | 11 schemas | 50+ tables

### 4.1 ENUM Types Dùng Chung

Các kiểu dữ liệu liệt kê được định nghĩa trong schema `public`, dùng chung cho tất cả schemas:

| Tên ENUM | Các giá trị | Ý nghĩa |
|---|---|---|
| `public.interval_type` | `'1m','5m','15m','30m','1H','4h','1D','1W','1M'` | Khung thời gian nến giá |
| `public.exchange_type` | `'HOSE','HNX','UPCOM','HNX_DERIVATIVE','UNKNOWN'` | Sàn giao dịch |
| `public.asset_type` | `'stock','etf','cw','futures','bond','index','unknown'` | Loại tài sản |
| `public.match_side` | `'buy','sell','atc','ato','unknown'` | Chiều khớp lệnh (mua/bán/ATC/ATO) |
| `public.period_type` | `'quarter','year'` | Kỳ báo cáo tài chính |
| `public.warrant_type` | `'call','put'` | Loại chứng quyền |
| `etl.run_status` | `'pending','running','success','partial','failed','skipped','timeout'` | Trạng thái job ETL |

---

### 4.2 Schema: `listing`

Quản lý danh mục mã chứng khoán, phân ngành ICB, nhóm chỉ số, lịch giao dịch và lịch sử đổi mã.

#### Bảng `listing.symbol` — Danh sách mã chứng khoán

Bảng master chứa tất cả mã giao dịch trên HOSE, HNX, UPCOM.
**Nguồn:** `Listing.all_symbols()` | **Cập nhật:** Mỗi thứ 2 lúc 7:00 AM

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) PK | Mã chứng khoán (VD: `VNM`, `VIC`, `ACB`) |
| `company_name` | TEXT | Tên công ty tiếng Việt |
| `company_name_en` | TEXT | Tên công ty tiếng Anh |
| `exchange` | exchange_type | Sàn giao dịch: HOSE / HNX / UPCOM |
| `asset_type` | asset_type | Loại tài sản: stock / etf / cw / bond |
| `icb_code` | VARCHAR(20) | Mã phân ngành ICB (liên kết → `listing.icb_industry`) |
| `is_active` | BOOLEAN | `TRUE` = đang giao dịch, `FALSE` = hủy niêm yết |
| `listing_date` | DATE | Ngày niêm yết |
| `delisting_date` | DATE | Ngày hủy niêm yết (nếu có) |
| `data_source` | VARCHAR(20) | Nguồn dữ liệu (VD: `VCI`) |
| `fetched_at` | TIMESTAMPTZ | Thời điểm lấy dữ liệu |
| `updated_at` | TIMESTAMPTZ | Thời điểm cập nhật gần nhất |

#### Bảng `listing.icb_industry` — Phân ngành ICB

Cây phân ngành ICB 4 cấp: Ngành → Siêu ngành → Lĩnh vực → Phân lĩnh vực.
**Nguồn:** `Listing.industries_icb()`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `icb_code` | VARCHAR(20) PK | Mã ICB (VD: `8000`, `8300`, `8350`) |
| `name_vn` | TEXT | Tên ngành tiếng Việt |
| `name_en` | TEXT | Tên ngành tiếng Anh |
| `level` | SMALLINT | Cấp độ 1–4 (1=Ngành lớn, 4=Phân lĩnh vực) |
| `parent_code` | VARCHAR(20) | Mã ICB cha (NULL nếu là cấp 1) |
| `data_source` | VARCHAR(20) | Nguồn dữ liệu |
| `fetched_at` | TIMESTAMPTZ | Thời điểm lấy dữ liệu |

#### Bảng `listing.symbol_group` — Nhóm chỉ số

Quan hệ nhiều-nhiều: 1 mã có thể thuộc nhiều nhóm (VD: VNM thuộc cả VN30 và VN100).

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) FK | Mã chứng khoán |
| `group_code` | VARCHAR(20) | Mã nhóm: `VN30`, `HNX30`, `VNMIDCAP`, `VNSMALLCAP`, `VN100`, `ETF`, `CW`... |
| `group_name` | TEXT | Tên đầy đủ của nhóm |
| `effective_date` | DATE | Ngày hiệu lực |
| `data_source` | VARCHAR(20) | Nguồn dữ liệu |

#### Bảng `listing.trading_calendar` — Lịch giao dịch

Lưu trữ các ngày giao dịch chính thức và thông tin phiên cho từng sàn.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `calendar_date` | DATE PK | Ngày giao dịch |
| `exchange` | exchange_type PK | Sàn (HOSE / HNX / UPCOM) |
| `is_trading_day` | BOOLEAN | `TRUE` nếu là ngày giao dịch |
| `session_open` | TIME | Giờ mở cửa (mặc định 09:00) |
| `session_close` | TIME | Giờ đóng cửa (mặc định 15:00) |
| `note` | TEXT | Ghi chú (VD: 'Tết Nguyên Đán', 'Half day') |

#### Bảng `listing.symbol_change` — Lịch sử đổi mã

Theo dõi đổi tên, hủy niêm yết, sáp nhập, chuyển sàn để đảm bảo tính liên tục dữ liệu lịch sử.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `old_symbol` | VARCHAR(20) | Mã cũ |
| `new_symbol` | VARCHAR(20) | Mã mới (NULL nếu hủy niêm yết / sáp nhập) |
| `change_date` | DATE | Ngày thay đổi |
| `change_type` | VARCHAR(20) | Loại thay đổi: `rename` / `delist` / `merge` / `transfer` |
| `note` | TEXT | Ghi chú lý do |

---

### 4.3 Schema: `market`

Toàn bộ dữ liệu giá và khối lượng giao dịch.

#### Bảng `market.ohlcv_daily` — Nến giá ngày (Phân vùng theo năm)

Dữ liệu OHLCV cho khung thời gian 1D, 1W, 1M. Phân vùng (partition) theo năm để truy vấn nhanh.
**Nguồn:** `Quote.history(symbol, start, end, interval='1D')`
**Partitions:** `ohlcv_daily_2022`, `ohlcv_daily_2023`, ..., `ohlcv_daily_2026`, `ohlcv_daily_future`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) PK | Mã chứng khoán |
| `interval` | interval_type PK | Khung thời gian: `1D` / `1W` / `1M` |
| `traded_at` | TIMESTAMPTZ PK | Thời điểm của nến (midnight Asia/Ho_Chi_Minh) |
| `exchange` | exchange_type | Sàn (để query thị trường mà không cần JOIN) |
| `open` | NUMERIC(18,4) | Giá mở cửa |
| `high` | NUMERIC(18,4) | Giá cao nhất |
| `low` | NUMERIC(18,4) | Giá thấp nhất |
| `close` | NUMERIC(18,4) | Giá đóng cửa |
| `volume` | BIGINT | Khối lượng khớp lệnh (cổ phiếu) |
| `value` | NUMERIC(24,0) | Giá trị khớp lệnh (VND) |
| `reference_price` | NUMERIC(18,4) | Giá tham chiếu |
| `ceiling_price` | NUMERIC(18,4) | Giá trần |
| `floor_price` | NUMERIC(18,4) | Giá sàn |
| `foreign_buy_vol` | BIGINT | Khối lượng khối ngoại mua |
| `foreign_sell_vol` | BIGINT | Khối lượng khối ngoại bán |
| `foreign_net_vol` | BIGINT | Khối lượng khối ngoại ròng (mua - bán) |
| `put_through_vol` | BIGINT | Khối lượng giao dịch thỏa thuận |
| `put_through_val` | NUMERIC(24,0) | Giá trị giao dịch thỏa thuận (VND) |
| `total_trades` | INT | Tổng số lệnh khớp trong ngày |
| `data_source` | VARCHAR(20) | Nguồn dữ liệu |
| `created_at` | TIMESTAMPTZ | Thời điểm ghi vào DB |

> **Chiến lược upsert:** `ON CONFLICT (symbol, interval, traded_at) DO NOTHING` — dữ liệu đã có không bị ghi đè.

#### Bảng `market.ohlcv_intraday` — Nến giá trong ngày (Phân vùng theo tháng)

Dữ liệu intraday: 1m, 5m, 15m, 30m, 1H, 4h. Phân vùng theo tháng.
**Scale:** ~15,6 triệu rows/tháng cho interval 1m với 1.785 mã.
**Partitions:** `ohlcv_intraday_2023_01` ... `ohlcv_intraday_2026_06`

Cấu trúc cột tương tự `ohlcv_daily` (không có các trường extended như ceiling/floor/foreign).

#### Bảng `market.intraday_trade` — Dữ liệu tick từng lệnh (Phân vùng theo ngày)

Dữ liệu từng lệnh khớp raw tick-by-tick. Scale ~3,6 triệu rows/ngày toàn thị trường.
**Nguồn:** `Quote.intraday(symbol, page_size, last_time)`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) PK | Mã chứng khoán |
| `traded_at` | TIMESTAMPTZ PK | Thời điểm khớp lệnh |
| `price` | NUMERIC(18,4) | Giá khớp |
| `volume` | BIGINT | Khối lượng khớp |
| `match_type` | match_side | Chiều lệnh: `buy` / `sell` / `atc` / `ato` / `unknown` |
| `trade_id` | VARCHAR(80) PK | ID lệnh từ nguồn (hoặc ID tổng hợp) |
| `price_change` | NUMERIC(18,4) | Biến động giá so với lệnh trước |
| `accum_volume` | BIGINT | Khối lượng lũy kế trong ngày |
| `accum_value` | NUMERIC(24,0) | Giá trị lũy kế trong ngày (VND) |

> **Lưu ý:** Cần `pg_partman` để tự động tạo và xóa partition hàng ngày.

#### Bảng `market.order_book_snapshot` — Sổ lệnh

Lưu 3 mức giá mua/bán tại một thời điểm.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã chứng khoán |
| `snapshot_at` | TIMESTAMPTZ | Thời điểm chụp sổ lệnh |
| `bid1_price/vol` | NUMERIC/BIGINT | Giá/KL mua tốt nhất (mức 1) |
| `bid2_price/vol` | NUMERIC/BIGINT | Giá/KL mua mức 2 |
| `bid3_price/vol` | NUMERIC/BIGINT | Giá/KL mua mức 3 |
| `ask1_price/vol` | NUMERIC/BIGINT | Giá/KL bán tốt nhất (mức 1) |
| `ask2_price/vol` | NUMERIC/BIGINT | Giá/KL bán mức 2 |
| `ask3_price/vol` | NUMERIC/BIGINT | Giá/KL bán mức 3 |

#### Bảng `market.index_ohlcv` — OHLCV chỉ số thị trường

Dữ liệu giá của các chỉ số: VNINDEX, VN30, HNX30, UPCOMINDEX, VNMIDCAP...

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `index_code` | VARCHAR(20) PK | Mã chỉ số (VD: `VNINDEX`, `VN30`) |
| `interval` | interval_type PK | Khung thời gian |
| `traded_at` | TIMESTAMPTZ PK | Thời điểm |
| `open/high/low/close` | NUMERIC | OHLCV của chỉ số (đơn vị điểm) |
| `advances` | INT | Số mã tăng điểm trong phiên |
| `declines` | INT | Số mã giảm điểm trong phiên |
| `unchanged` | INT | Số mã đứng giá |

#### Bảng `market.market_breadth` — Độ rộng thị trường

Thống kê tổng hợp mỗi ngày cho từng sàn.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `trade_date` | DATE PK | Ngày giao dịch |
| `exchange` | exchange_type PK | Sàn |
| `advances` | INT | Số mã tăng |
| `declines` | INT | Số mã giảm |
| `unchanged` | INT | Số mã đứng |
| `total_trading` | INT | Tổng số mã có giao dịch |
| `total_volume` | BIGINT | Tổng khối lượng toàn sàn |
| `total_value` | NUMERIC(24,0) | Tổng giá trị toàn sàn (VND) |
| `new_highs_52w` | INT | Số mã lập đỉnh 52 tuần |
| `new_lows_52w` | INT | Số mã lập đáy 52 tuần |
| `foreign_net_vol` | BIGINT | KL ròng khối ngoại toàn sàn |
| `foreign_net_val` | NUMERIC(24,0) | GT ròng khối ngoại toàn sàn |

#### Bảng `market.trading_halt` — Tạm dừng giao dịch

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK bị tạm dừng |
| `halt_date` | DATE | Ngày bị tạm dừng |
| `resume_date` | DATE | Ngày giao dịch trở lại (NULL nếu chưa) |
| `halt_type` | VARCHAR(20) | Loại: `NG`=cảnh báo, `DL`=kiểm soát, `KH`=tạm dừng, `HUY`=hủy niêm yết |
| `reason` | TEXT | Lý do tạm dừng |

#### Bảng `market.price_adjustment` — Hệ số điều chỉnh giá

Hệ số điều chỉnh giá lịch sử cho các sự kiện công ty (tách cổ phiếu, cổ tức...).

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `ex_date` | DATE | Ngày giao dịch không hưởng quyền |
| `action_type` | VARCHAR(30) | Loại sự kiện: `split` / `bonus` / `rights` / `cash_dividend` |
| `adj_factor` | NUMERIC(16,10) | Hệ số nhân giá (VD: tách 1:2 → `adj_factor = 0.5`) |
| `vol_factor` | NUMERIC(16,10) | Hệ số nhân khối lượng |
| `raw_value` | NUMERIC(18,4) | Giá trị gốc (cổ tức/cổ phiếu, tỷ lệ thưởng...) |

---

### 4.4 Schema: `derivatives`

Thông tin hợp đồng phái sinh và chứng quyền có đảm bảo.

#### Bảng `derivatives.futures_profile` — Hợp đồng Tương Lai

**Nguồn:** `Listing.all_future_indices()`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `contract_code` | VARCHAR(20) PK | Mã hợp đồng (VD: `VN30F2503`, `VN30F2506`) |
| `underlying_symbol` | VARCHAR(20) | Tài sản cơ sở (mặc định `VN30`) |
| `exchange` | exchange_type | Sàn giao dịch (`HNX_DERIVATIVE`) |
| `issue_date` | DATE | Ngày phát hành |
| `first_trading_date` | DATE | Ngày giao dịch đầu tiên |
| `last_trading_date` | DATE | Ngày giao dịch cuối cùng |
| `maturity_date` | DATE | Ngày đáo hạn |
| `contract_multiplier` | NUMERIC | Hệ số nhân (100.000 VND/điểm) |
| `tick_size` | NUMERIC | Bước giá nhỏ nhất (0,1 điểm) |
| `initial_margin` | NUMERIC | Ký quỹ ban đầu (VND) |
| `is_active` | BOOLEAN | Còn hiệu lực giao dịch không |

#### Bảng `derivatives.warrant_profile` — Chứng Quyền Có Đảm Bảo (CW)

**Nguồn:** `Listing.all_covered_warrant()`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) PK | Mã CW (VD: `CHPG2201`, `CVHM2301`) |
| `issuer` | TEXT | Tổ chức phát hành (SSI, VCI, MBS...) |
| `underlying_symbol` | VARCHAR(20) | Mã CK cơ sở |
| `exercise_price` | NUMERIC(18,4) | Giá thực hiện (VND) |
| `exercise_ratio` | NUMERIC(12,6) | Tỷ lệ chuyển đổi (số CW cần để nhận 1 cổ phiếu) |
| `warrant_type` | warrant_type | Loại: `call` / `put` |
| `maturity_date` | DATE | Ngày đáo hạn |
| `listed_shares` | BIGINT | Số CW đang lưu hành |
| `break_even_point` | NUMERIC(18,4) | Giá hòa vốn (điểm cân bằng) |
| `intrinsic_value` | NUMERIC(18,4) | Giá trị nội tại |

---

### 4.5 Schema: `company`

Thông tin doanh nghiệp niêm yết.

#### Bảng `company.profile` — Hồ sơ công ty

**Nguồn:** `Company.overview()` | **Versioned:** mỗi lần fetch tạo 1 snapshot mới.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) FK | Mã CK |
| `company_name` | TEXT | Tên công ty tiếng Việt |
| `company_name_en` | TEXT | Tên công ty tiếng Anh |
| `exchange` | exchange_type | Sàn |
| `icb_code` | VARCHAR(20) | Mã ngành ICB |
| `founded_date` | DATE | Ngày thành lập |
| `listing_date` | DATE | Ngày niêm yết |
| `charter_capital` | NUMERIC(24,0) | Vốn điều lệ (VND) |
| `issued_shares` | BIGINT | Số cổ phiếu đang lưu hành |
| `num_employees` | INT | Số nhân viên |
| `website` | TEXT | Website công ty |
| `tax_code` | VARCHAR(20) | Mã số thuế |
| `address` | TEXT | Địa chỉ |
| `business_model` | TEXT | Mô hình kinh doanh |
| `description` | TEXT | Mô tả hoạt động kinh doanh |
| `raw_data` | JSONB | Toàn bộ dữ liệu gốc từ API (để tra cứu các trường khác) |
| `fetched_at` | TIMESTAMPTZ | Thời điểm fetch (dùng để lấy snapshot mới nhất) |

> **Query lấy snapshot mới nhất:**
> `SELECT DISTINCT ON (symbol) * FROM company.profile ORDER BY symbol, fetched_at DESC`

#### Bảng `company.shareholder` — Cổ đông lớn

**Nguồn:** `Company.shareholders()`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `shareholder_name` | TEXT | Tên cổ đông |
| `shares` | BIGINT | Số cổ phiếu nắm giữ |
| `ownership_pct` | NUMERIC(10,6) | Tỷ lệ sở hữu (%) |
| `report_date` | DATE | Ngày báo cáo |

#### Bảng `company.officer` — Ban lãnh đạo

**Nguồn:** `Company.officers()`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `full_name` | TEXT | Họ và tên |
| `position_vn` | TEXT | Chức vụ tiếng Việt |
| `position_en` | TEXT | Chức vụ tiếng Anh |
| `from_date` | DATE | Ngày bắt đầu đảm nhiệm |
| `to_date` | DATE | Ngày kết thúc (NULL nếu đang đương nhiệm) |
| `is_active` | BOOLEAN | Còn đương nhiệm không |
| `owned_shares` | BIGINT | Số CP cá nhân nắm giữ |
| `ownership_pct` | NUMERIC(10,6) | Tỷ lệ nắm giữ (%) |

#### Bảng `company.subsidiary` — Công ty con / Liên kết

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `parent_symbol` | VARCHAR(20) | Mã công ty mẹ |
| `sub_name` | TEXT | Tên công ty con/liên kết |
| `charter_capital` | NUMERIC(24,0) | Vốn điều lệ |
| `ownership_pct` | NUMERIC(10,6) | Tỷ lệ sở hữu của công ty mẹ (%) |
| `relation_type` | VARCHAR(40) | `cong_ty_con` (>50%) hoặc `cong_ty_lien_ket` (≤50%) |

#### Bảng `company.event` — Sự kiện công ty

**Nguồn:** `Company.events()`

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `event_type` | SMALLINT | 1=ĐHCĐ, 2=Cổ tức, 3=Phát hành, 4=GDNB, 5=Khác |
| `event_type_name` | VARCHAR(80) | Tên loại sự kiện |
| `event_date` | DATE | Ngày tổ chức sự kiện |
| `ex_date` | DATE | Ngày giao dịch không hưởng quyền |
| `record_date` | DATE | Ngày chốt danh sách |
| `payment_date` | DATE | Ngày thanh toán (với cổ tức) |
| `title` | TEXT | Tiêu đề sự kiện |
| `value` | NUMERIC(18,4) | Giá trị (VD: cổ tức VND/cổ phiếu) |
| `raw_data` | JSONB | Dữ liệu gốc đầy đủ |

#### Bảng `company.news` — Tin tức công ty

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `published_at` | TIMESTAMPTZ | Thời điểm đăng tin |
| `title` | TEXT | Tiêu đề bài viết |
| `summary` | TEXT | Tóm tắt |
| `url` | TEXT | Đường dẫn bài viết |
| `source_name` | TEXT | Tên nguồn tin |

#### Bảng `company.insider_trade` — Giao dịch nội bộ

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `trader_name` | TEXT | Tên người giao dịch nội bộ |
| `position` | TEXT | Chức vụ |
| `transaction_date` | DATE | Ngày giao dịch |
| `method` | VARCHAR(60) | Phương thức: khớp lệnh, thỏa thuận... |
| `volume_registered` | BIGINT | Khối lượng đăng ký |
| `volume_executed` | BIGINT | Khối lượng thực hiện |
| `before_shares/pct` | BIGINT/NUMERIC | Số CP / tỷ lệ trước giao dịch |
| `after_shares/pct` | BIGINT/NUMERIC | Số CP / tỷ lệ sau giao dịch |

#### Bảng `company.capital_history` — Lịch sử vốn điều lệ

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `event_date` | DATE | Ngày thay đổi vốn |
| `capital_vnd` | NUMERIC(24,0) | Vốn điều lệ tại thời điểm đó (VND) |
| `note` | TEXT | Ghi chú lý do thay đổi |

#### Bảng `company.stock_split` — Lịch sử tách/gộp cổ phiếu

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `ex_date` | DATE | Ngày thực hiện |
| `split_type` | VARCHAR(20) | `split` / `bonus` / `consolidation` |
| `split_ratio` | NUMERIC(12,6) | Tỷ lệ: số CP mới / số CP cũ (VD: 2.0 = tách 1:2) |

---

### 4.6 Schema: `finance`

Báo cáo tài chính theo mô hình **EAV (Entity-Attribute-Value)**.

> **Tại sao dùng EAV?**
> vnstock trả về 80-100 chỉ tiêu tài chính mỗi loại BCTC. Dùng EAV tránh bảng 100 cột và không cần migration khi có chỉ tiêu mới.
> **Query mẫu:** `WHERE symbol='VNM' AND item_id='net_revenue' ORDER BY period_label DESC`

Cấu trúc chung của 4 bảng finance:

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `period_type` | period_type | Kỳ báo cáo: `quarter` hoặc `year` |
| `period_label` | VARCHAR(12) | Nhãn kỳ: `'2024'` (năm) hoặc `'2024-Q1'` (quý) |
| `year` | SMALLINT | Năm tài chính |
| `quarter` | SMALLINT | Quý (1-4), NULL nếu báo cáo năm |
| `item_id` | VARCHAR(120) | ID chỉ tiêu dạng snake_case (VD: `net_revenue`, `total_assets`) |
| `item_vn` | TEXT | Tên chỉ tiêu tiếng Việt |
| `item_en` | TEXT | Tên chỉ tiêu tiếng Anh |
| `value` | NUMERIC(28,4) | Giá trị (đơn vị tỷ VND) |
| `unit` | VARCHAR(20) | Đơn vị (mặc định `billion_vnd`) |
| `row_order` | SMALLINT | Thứ tự dòng trong BCTC gốc |
| `hierarchy_level` | SMALLINT | Cấp độ thụt lề trong BCTC (0=tổng, 1=khoản mục, 2=chi tiết) |
| `is_audited` | BOOLEAN | Đã kiểm toán hay chưa |

**4 bảng trong schema `finance`:**

| Bảng | Nguồn vnstock | Nội dung |
|---|---|---|
| `finance.income_statement` | `Finance.income_statement()` | Báo cáo kết quả kinh doanh (doanh thu, lợi nhuận...) |
| `finance.balance_sheet` | `Finance.balance_sheet()` | Bảng cân đối kế toán (tài sản, nợ, vốn chủ sở hữu) |
| `finance.cash_flow` | `Finance.cash_flow()` | Báo cáo lưu chuyển tiền tệ (HĐKD, HĐĐT, HĐTC) |
| `finance.financial_ratio` | `Finance.ratio()` | Các chỉ số tài chính (P/E, ROE, ROA, EPS...) |

`cash_flow` có thêm cột `cash_flow_method` = `'indirect'` hoặc `'direct'` (phương pháp lập BCTC).
`financial_ratio` có thêm cột `ratio_group` = `'valuation'`, `'profitability'`, `'growth'`, `'liquidity'`, `'asset_quality'`.

---

### 4.7 Schema: `trading`

Dữ liệu giao dịch nâng cao: khối ngoại, thỏa thuận, lô lẻ, thống kê ngày.

#### Bảng `trading.foreign_flow` — Giao dịch khối ngoại

**Nguồn:** `Trading.foreign_trade()` | **Cập nhật:** Thứ 2-6, 17:45

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `trade_date` | DATE | Ngày giao dịch |
| `buy_volume` | BIGINT | KL khối ngoại mua |
| `buy_value` | NUMERIC(24,0) | GT khối ngoại mua (VND) |
| `sell_volume` | BIGINT | KL khối ngoại bán |
| `sell_value` | NUMERIC(24,0) | GT khối ngoại bán (VND) |
| `net_volume` | BIGINT | KL ròng (mua - bán) |
| `net_value` | NUMERIC(24,0) | GT ròng (VND) |
| `room_remaining` | BIGINT | Tỷ lệ sở hữu nước ngoài còn lại (foreign room) |

#### Bảng `trading.block_trade` — Giao dịch thỏa thuận

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `traded_at` | TIMESTAMPTZ | Thời điểm giao dịch |
| `price` | NUMERIC(18,4) | Giá thỏa thuận |
| `volume` | BIGINT | Khối lượng |
| `buyer_code` | VARCHAR(40) | Mã công ty chứng khoán bên mua |
| `seller_code` | VARCHAR(40) | Mã công ty chứng khoán bên bán |

#### Bảng `trading.odd_lot_trade` — Giao dịch lô lẻ

Giao dịch dưới 100 cổ phiếu (lô lẻ), khớp lệnh theo cơ chế riêng của sàn.

#### Bảng `trading.trading_stat` — Thống kê giao dịch ngày

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) | Mã CK |
| `trade_date` | DATE | Ngày giao dịch |
| `total_volume` | BIGINT | Tổng KL trong ngày |
| `total_value` | NUMERIC(24,0) | Tổng GT trong ngày (VND) |
| `avg_price` | NUMERIC(18,4) | Giá bình quân trong ngày |
| `total_trades` | INT | Số lệnh khớp |
| `buy_volume` | BIGINT | KL lệnh chủ động mua |
| `sell_volume` | BIGINT | KL lệnh chủ động bán |

#### Bảng `trading.price_board_snapshot` — Bảng giá real-time

Chụp nhanh toàn bộ bảng giá tại một thời điểm trong phiên giao dịch.

---

### 4.8 Schema: `index_data`

#### Bảng `index_data.index_list` — Danh sách chỉ số

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `index_code` | VARCHAR(20) PK | Mã chỉ số (VD: `VNINDEX`, `VN30`, `HNX30`) |
| `index_name` | TEXT | Tên đầy đủ |
| `exchange` | exchange_type | Sàn quản lý |
| `num_components` | INT | Số mã thành phần |

#### Bảng `index_data.index_constituent` — Thành phần chỉ số

Theo dõi lịch sử các mã vào/ra chỉ số.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `index_code` | VARCHAR(20) PK | Mã chỉ số |
| `symbol` | VARCHAR(20) PK | Mã CK thành phần |
| `weight_pct` | NUMERIC(10,6) | Tỷ trọng trong chỉ số (%) |
| `free_float_pct` | NUMERIC(10,6) | Tỷ lệ cổ phiếu tự do chuyển nhượng (%) |
| `effective_date` | DATE PK | Ngày vào chỉ số |
| `removal_date` | DATE | Ngày ra khỏi chỉ số |
| `is_active` | BOOLEAN | Còn trong chỉ số không |

---

### 4.9 Schema: `fund`

Dữ liệu quỹ đầu tư từ Fmarket.

#### Bảng `fund.fund` — Danh sách quỹ

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `fund_id` | INT PK | ID nội bộ Fmarket |
| `short_name` | VARCHAR(20) | Ticker quỹ (VD: `SSISCA`, `VFMVSF`) |
| `fund_type` | VARCHAR(20) | Loại quỹ: `equity_fund` / `bond_fund` / `balanced_fund` |
| `issuer` | TEXT | Công ty quản lý quỹ |
| `nav_per_unit` | NUMERIC(18,4) | NAV/chứng chỉ quỹ hiện tại |
| `nav_1m/3m/6m/1y/3y_pct` | NUMERIC(10,6) | Hiệu suất NAV 1T, 3T, 6T, 1N, 3N (%) |

#### Bảng `fund.nav_history` — Lịch sử NAV (Phân vùng theo năm)

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `fund_id` | INT PK FK | ID quỹ |
| `nav_date` | DATE PK | Ngày NAV |
| `nav_per_unit` | NUMERIC(18,4) | Giá trị NAV/chứng chỉ quỹ tại ngày đó |

#### Bảng `fund.top_holding` — Danh mục đầu tư top

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `fund_id` | INT | Quỹ |
| `stock_code` | VARCHAR(20) | Mã CK đang nắm giữ |
| `net_asset_pct` | NUMERIC(10,6) | Tỷ lệ NAV đầu tư vào mã này (%) |
| `asset_type` | VARCHAR(20) | `equity` / `bond` |
| `reported_at` | DATE | Ngày báo cáo |

---

### 4.10 Schema: `macro`

Dữ liệu kinh tế vĩ mô.

#### Bảng `macro.exchange_rate` — Tỷ giá ngoại tệ

**Nguồn:** VCB (Vietcombank) tỷ giá hàng ngày

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `rate_date` | DATE PK | Ngày áp dụng |
| `currency_code` | VARCHAR(10) PK | Mã tiền tệ (USD, EUR, JPY...) |
| `buy_cash` | NUMERIC(18,4) | Giá mua tiền mặt (VND) |
| `buy_transfer` | NUMERIC(18,4) | Giá mua chuyển khoản (VND) |
| `sell` | NUMERIC(18,4) | Giá bán (VND) |

#### Bảng `macro.economic_indicator` — Chỉ số kinh tế (EAV)

Dùng mô hình EAV để lưu linh hoạt nhiều loại chỉ số kinh tế: GDP, CPI, FDI, M2, lãi suất repo...

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `indicator_code` | VARCHAR(40) | Mã chỉ số: `GDP`, `CPI`, `FDI_REGISTERED`, `M2`, `REPO_RATE`... |
| `period_label` | VARCHAR(20) | Kỳ: `'2024'`, `'2024-Q1'`, `'2024-01'` |
| `period_start/end` | DATE | Khoảng thời gian |
| `value` | NUMERIC(28,8) | Giá trị |
| `unit` | VARCHAR(40) | Đơn vị: `%`, `billion_usd`, `trillion_vnd`... |
| `yoy_change_pct` | NUMERIC(12,6) | Tăng trưởng so với cùng kỳ năm trước (%) |
| `raw_data` | JSONB | Dữ liệu gốc đầy đủ |

---

### 4.11 Schema: `commodity`

Giá hàng hóa trong và ngoài nước.

#### Bảng `commodity.gold_price` — Giá vàng

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `price_date` | DATE | Ngày |
| `provider` | VARCHAR(20) | Đơn vị cung cấp: `SJC`, `BTMC`, `GLOBAL` |
| `gold_type` | VARCHAR(80) | Loại vàng: `Vàng miếng SJC`, `Vàng nhẫn 9999`... |
| `karat` | VARCHAR(10) | Tuổi vàng (24K, 22K...) |
| `buy_price` | NUMERIC(18,2) | Giá mua (VND) |
| `sell_price` | NUMERIC(18,2) | Giá bán (VND) |
| `world_price` | NUMERIC(18,4) | Giá vàng thế giới tham chiếu (USD/ounce) |

#### Bảng `commodity.commodity_price` — Giá hàng hóa khác

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `commodity_code` | VARCHAR(40) | Mã hàng hóa: `RON95`, `RON92`, `DO_0_05S`, `STEEL_D10`, `UREA`... |
| `commodity_name` | TEXT | Tên hàng hóa |
| `price` | NUMERIC(18,4) | Giá |
| `unit` | VARCHAR(30) | Đơn vị: `VND/liter`, `VND/kg`... |
| `region` | VARCHAR(40) | Khu vực: `HCM`, `HN`, `national`, `global` |

---

### 4.12 Schema: `etl`

Hệ thống theo dõi và điều phối pipeline nội bộ.

#### Bảng `etl.collection_tier` — Phân cấp thu thập dữ liệu

Định nghĩa chiến lược thu thập cho từng nhóm mã CK.

| Tier | Tên | Mã | Dữ liệu thu thập |
|---|---|---|---|
| **1** | `liquid_vn30` | VN30 | OHLCV 1D + intraday (1m/5m/15m/1H) + tick + order book + công ty + BCTC + ngoại |
| **2** | `mid_cap` | VN100 trừ VN30 | OHLCV 1D + intraday (5m/15m) + công ty + BCTC + ngoại |
| **3** | `small_cap_listed` | HOSE+HNX còn lại | OHLCV 1D + công ty + BCTC + ngoại |
| **4** | `upcom` | UPCOM | OHLCV 1D only |
| **5** | `derivatives` | Futures + CW | OHLCV 1D + intraday (1m/5m) + tick |

Seed ban đầu trong tier 1: VNM, FPT, VIC, VHM, TCB, VCB, MWG, HPG, MSN, VRE, SSI, HDB, VPB, ACB, BID.

#### Bảng `etl.symbol_collection_config` — Cấu hình thu thập mỗi symbol

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) PK | Mã CK |
| `tier` | SMALLINT FK | Thuộc tier nào |
| `is_active` | BOOLEAN | Đang được thu thập không |
| `override_*` | BOOLEAN | Ghi đè cấu hình tier (NULL = theo mặc định của tier) |
| `priority` | SMALLINT | Ưu tiên (1=cao nhất, 10=thấp nhất) |

#### Bảng `etl.job_definition` — Danh sách tất cả jobs (31 jobs)

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `job_id` | VARCHAR(80) PK | ID job (VD: `fetch_ohlcv_daily_all`) |
| `job_name` | TEXT | Tên mô tả |
| `job_category` | VARCHAR(40) | Nhóm: `market`, `company`, `finance`, `trading`, `listing`, `macro`, `fund`, `commodity` |
| `job_type` | VARCHAR(20) | `scheduled` / `bootstrap` / `manual` |
| `cron_expression` | VARCHAR(80) | Biểu thức cron (VD: `'15 16 * * MON-FRI'`) |
| `timeout_seconds` | INT | Timeout tối đa (mặc định 300 giây) |
| `max_retries` | SMALLINT | Số lần thử lại khi lỗi |
| `target_tier` | SMALLINT | Chỉ chạy cho tier nào (NULL = tất cả) |
| `is_enabled` | BOOLEAN | Job có đang được kích hoạt không |

#### Bảng `etl.job_run` — Nhật ký thực thi job

Mỗi lần job chạy tạo 1 bản ghi. Dùng để theo dõi lịch sử, thống kê hiệu suất.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `job_id` | VARCHAR(80) FK | ID job |
| `run_at` | TIMESTAMPTZ | Thời điểm bắt đầu |
| `finished_at` | TIMESTAMPTZ | Thời điểm kết thúc |
| `duration_ms` | INT | Thời gian chạy (mili-giây) |
| `status` | run_status | Trạng thái: `success` / `failed` / `partial` / `timeout`... |
| `symbol` | VARCHAR(20) | Symbol cụ thể (NULL nếu chạy toàn bộ) |
| `date_from / date_to` | DATE | Khoảng ngày đã xử lý |
| `rows_fetched` | INT | Số bản ghi lấy từ API |
| `rows_inserted` | INT | Số bản ghi mới thêm vào DB |
| `rows_updated` | INT | Số bản ghi cập nhật |
| `rows_skipped` | INT | Số bản ghi bỏ qua (đã có) |
| `error_message` | TEXT | Thông báo lỗi (nếu có) |
| `error_traceback` | TEXT | Stack trace lỗi đầy đủ |
| `host_name` | VARCHAR(100) | Máy chủ chạy job |
| `pid` | INT | Process ID |

#### Bảng `etl.data_freshness` — Độ tươi dữ liệu

Theo dõi trạng thái dữ liệu cho từng cặp (symbol, data_type).

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `symbol` | VARCHAR(20) PK | Mã CK (`_global_` cho dữ liệu không theo mã) |
| `data_type` | VARCHAR(60) PK | Loại: `ohlcv_daily.1D`, `ohlcv_intraday.1m`, `company.profile`... |
| `earliest_date` | DATE | Ngày sớm nhất có dữ liệu |
| `latest_date` | DATE | Ngày mới nhất có dữ liệu |
| `row_count` | BIGINT | Tổng số bản ghi |
| `is_bootstrapped` | BOOLEAN | Đã hoàn thành fetch lịch sử ban đầu chưa |
| `last_successful_fetch` | TIMESTAMPTZ | Lần fetch thành công gần nhất |
| `consecutive_failures` | SMALLINT | Số lần thất bại liên tiếp |

#### Bảng `etl.pipeline_state` — Trạng thái toàn cục pipeline

Key-value store cho các flag điều phối hệ thống.

| Key | Ý nghĩa |
|---|---|
| `bootstrap_completed` | Pipeline đã hoàn thành bootstrap lần đầu chưa |
| `scheduler_running` | Scheduler hiện đang chạy không |
| `listing_last_synced` | Lần cuối sync danh sách mã |
| `calendar_last_synced` | Lần cuối sync lịch giao dịch |

#### Bảng `etl.schedule_override` — Ghi đè lịch chạy

Cho phép tạm dừng, đổi lịch, hoặc ép chạy 1 job mà không cần thay code.

| `override_type` | Hành động |
|---|---|
| `pause` | Tạm dừng job cho đến `effective_until` |
| `reschedule` | Chạy theo `new_cron_expr` thay vì lịch mặc định |
| `force_run` | Ép chạy ngay lập tức |

---

## 5. Các Extractor — Tầng Trích Xuất Dữ Liệu

Tất cả extractor đều gọi thư viện **vnstock** (nguồn VCI) và trả về **pandas DataFrame**.

| Class | File | API vnstock | Dữ liệu trả về |
|---|---|---|---|
| `ListingExtractor` | `extractors/listing_extractor.py` | `Listing.all_symbols()` | DataFrame: symbol, tên công ty, sàn, ICB code |
| | | `Listing.industries_icb()` | DataFrame: ICB code, tên ngành, cấp, mã cha |
| `MarketExtractor` | `extractors/market_extractor.py` | `Quote.history(symbol, start, end, interval='1D')` | DataFrame: date, open, high, low, close, volume, value |
| `CompanyExtractor` | `extractors/company_extractor.py` | `Company.overview(symbol)` | DataFrame: thông tin tổng quan công ty |
| | | `Company.shareholders(symbol)` | DataFrame: danh sách cổ đông |
| | | `Company.officers(symbol)` | DataFrame: ban lãnh đạo |
| | | `Company.events(symbol)` | DataFrame: sự kiện công ty |
| `FinanceExtractor` | `extractors/finance_extractor.py` | `Finance.income_statement(period, lang='en')` | DataFrame dọc: item × kỳ |
| | | `Finance.balance_sheet(period, lang='en')` | Tương tự |
| | | `Finance.cash_flow(period, lang='en')` | Tương tự |
| | | `Finance.ratio(period, lang='en')` | Tương tự |
| `TradingExtractor` | `extractors/trading_extractor.py` | `Trading.foreign_trade(start, end)` | DataFrame: ngày, mua, bán, ròng, room |

---

## 6. Các Transformer — Tầng Chuyển Đổi Dữ Liệu

Transformer nhận **pandas DataFrame** → trả về **`list[dict]`** tương thích với schema DB.

| Class | Nhiệm vụ chính |
|---|---|
| `ListingTransformer` | Map tên cột vnstock → tên cột DB. Chuẩn hóa exchange (`HSX`→`HOSE`), asset_type, parse ngày. |
| `MarketTransformer` | Map cột OHLCV linh hoạt (nhiều nguồn khác nhau). Ép kiểu `_safe_float()`, `_safe_int()`. Xử lý giá trị None. |
| `CompanyTransformer` | Trích xuất các trường chuẩn hóa + lưu toàn bộ raw DataFrame vào `raw_data` (JSONB). |
| `FinanceTransformer` | Chuyển DataFrame dạng wide (cột = kỳ, hàng = chỉ tiêu) → EAV dọc (mỗi hàng = 1 chỉ tiêu, 1 kỳ). Parse kỳ từ nhiều định dạng: `'2024'`, `'2024-Q1'`, `'Q1-2024'`, `'2024Q1'`. |
| `TradingTransformer` | Map cột foreign flow linh hoạt, ép kiểu an toàn cho volume và value. |

**Kỹ thuật chuyển đổi quan trọng của FinanceTransformer:**

```
DataFrame đầu vào (wide format):
         item_name   | 2024-Q4 | 2024-Q3 | 2024-Q2
  -------------------|---------|---------|--------
  Net Revenue        | 15000   | 14500   | 13800
  Gross Profit       |  5200   |  4900   |  4700

       ▼ transform_income_statement()

list[dict] đầu ra (EAV / long format):
  {symbol, period_type='quarter', period_label='2024-Q4', year=2024, quarter=4,
   item_id='net_revenue', item_en='Net Revenue', value=15000.0, ...}
  {symbol, period_type='quarter', period_label='2024-Q4', year=2024, quarter=4,
   item_id='gross_profit', item_en='Gross Profit', value=5200.0, ...}
  ...
```

---

## 7. Các Loader & Repository — Tầng Lưu Trữ

### Loaders (`loaders/`)

Mỗi loader là lớp trung gian gọi repository để upsert dữ liệu.

| Class | Method chính | Repository được gọi |
|---|---|---|
| `ListingLoader` | `load_symbols()`, `load_icb_industries()` | `ListingRepository` |
| `MarketLoader` | `load_ohlcv_daily()`, `get_latest_date()` | `MarketRepository` |
| `CompanyLoader` | `load_profile()`, `load_shareholders()`, `load_officers()`, `load_events()` | `CompanyRepository` |
| `FinanceLoader` | `load_income_statement()`, `load_balance_sheet()`, `load_cash_flow()`, `load_financial_ratios()` | `FinanceRepository` |
| `TradingLoader` | `load_foreign_flow()` | `TradingRepository` |
| `BaseLoader` | `connect()`, `tracked_job()` | `EtlRepository` |

**`BaseLoader` — Quản lý kết nối và tracking:**

```python
# Context manager kết nối DB
with BaseLoader.connect() as conn:
    repo = ListingRepository(conn)
    symbols = repo.get_all_symbols()

# Context manager theo dõi job (tự động ghi vào etl.job_run)
with BaseLoader.tracked_job(job_id='fetch_ohlcv_daily_all') as tracker:
    tracker.rows_inserted += MarketLoader.load_ohlcv_daily(records)
```

### Repositories (`db/repositories/`)

Thực thi SQL trực tiếp qua SQLAlchemy. Chiến lược upsert:

| Repository | Bảng | Chiến lược xung đột |
|---|---|---|
| `ListingRepository` | `listing.symbol`, `listing.icb_industry` | `ON CONFLICT DO UPDATE SET` (cập nhật trường mới) |
| `MarketRepository` | `market.ohlcv_daily` | `ON CONFLICT DO NOTHING` (không ghi đè giá đã có) |
| `CompanyRepository` | `company.profile` | Insert mới (versioned theo `fetched_at`) |
| `CompanyRepository` | `company.shareholder`, `company.officer`, `company.event` | `ON CONFLICT DO UPDATE SET` |
| `FinanceRepository` | `finance.*` | `ON CONFLICT DO UPDATE SET value = EXCLUDED.value` |
| `TradingRepository` | `trading.foreign_flow` | `ON CONFLICT DO UPDATE SET` (cập nhật nếu có thay đổi) |
| `EtlRepository` | `etl.job_run`, `etl.data_freshness` | Insert mới (job_run) / `ON CONFLICT DO UPDATE` (freshness) |

**Incremental update (tránh fetch lại dữ liệu cũ):**

```python
# MarketLoader kiểm tra ngày mới nhất trước khi fetch
latest = MarketLoader.get_latest_date(symbol, "1D")
# → SELECT MAX(traded_at) FROM market.ohlcv_daily WHERE symbol=? AND interval=?

if latest:
    start_date = latest + 1 day  # chỉ fetch từ ngày tiếp theo
else:
    start_date = today - 1095 days  # fetch 3 năm lịch sử lần đầu
```

---

## 8. Các Jobs — Chi Tiết Từng Công Việc

### Job 1: `job_sync_listing` — Đồng bộ danh sách mã CK

**File:** `jobs/listing_jobs.py`
**Lịch:** Mỗi thứ 2, 7:00 AM + mỗi lần bootstrap

**Luồng:**
```
1. ListingExtractor.extract_all_symbols()     → ~1.738 symbols
2. ListingTransformer.transform_symbols()     → list[dict] chuẩn hóa
3. ListingLoader.load_symbols()               → upsert vào listing.symbol

4. ListingExtractor.extract_industries_icb()  → ~155 ngành ICB
5. ListingTransformer.transform_industries_icb() → list[dict]
6. ListingLoader.load_icb_industries()        → upsert vào listing.icb_industry
```

---

### Job 2: `job_fetch_ohlcv_daily` — Lấy giá OHLCV ngày

**File:** `jobs/market_jobs.py`
**Lịch:** Thứ 2-6, 17:30
**Tham số bổ sung (cho backfill):** `start_date`, `end_date`, `symbols_filter`

**Logic incremental:**
- Nếu symbol đã có data: fetch từ ngày cuối cùng + 1
- Nếu chưa có data: fetch 3 năm (1.095 ngày) về trước
- Xử lý theo batch 50 symbols, sleep 0.3 giây/symbol để tránh rate limit

---

### Job 3: `job_fetch_company_profiles` — Thông tin công ty

**File:** `jobs/company_jobs.py`
**Lịch:** Thứ 2, 8:00 AM
**Tham số bổ sung (cho backfill):** `symbols_filter`

**Dữ liệu thu thập cho mỗi symbol:**
1. Overview (tổng quan công ty)
2. Shareholders (danh sách cổ đông lớn)
3. Officers (ban lãnh đạo)
4. Events (sự kiện công ty)

Sleep 0.5 giây/symbol.

---

### Job 4: `job_fetch_financial_statements` — Báo cáo tài chính

**File:** `jobs/finance_jobs.py`
**Lịch:** Ngày 1 mỗi tháng, 9:00 AM
**Tham số bổ sung (cho backfill):** `symbols_filter`

**Dữ liệu thu thập cho mỗi symbol:**
1. Income Statement (KQKD — Doanh thu, Lợi nhuận...)
2. Balance Sheet (CĐKT — Tài sản, Nợ, Vốn...)
3. Cash Flow (LCTT — Tiền từ HĐ kinh doanh/đầu tư/tài chính)
4. Financial Ratios (P/E, ROE, ROA, EPS, D/E...)

Mặc định lấy theo kỳ quý (`period='quarter'`). Sleep 0.5 giây/symbol.

---

### Job 5: `job_fetch_foreign_flow` — Giao dịch khối ngoại

**File:** `jobs/trading_jobs.py`
**Lịch:** Thứ 2-6, 17:45
**Tham số bổ sung (cho backfill):** `start_date`, `end_date`, `symbols_filter`

**Logic mặc định:** Fetch 30 ngày gần nhất cho tất cả symbols.
Sleep 0.3 giây/symbol.

---

## 9. Dữ Liệu Thu Thập & Scale

### Ước tính khối lượng dữ liệu theo năm

| Loại dữ liệu | Bảng | Rows/năm | Partition |
|---|---|---|---|
| OHLCV ngày (1D) | `market.ohlcv_daily` | ~446.000 | Theo năm |
| OHLCV 1 phút | `market.ohlcv_intraday` | ~187.000.000 | Theo tháng |
| Tick data | `market.intraday_trade` | ~900.000.000 | Theo ngày |
| Foreign flow | `trading.foreign_flow` | ~446.000 | Không phân vùng |
| BCTC (EAV) | `finance.*` | ~800.000 | Không phân vùng |
| Company profiles | `company.profile` | ~1.785 snapshot/tuần | Không phân vùng |

### Ước tính dung lượng

| Loại | Dung lượng/năm |
|---|---|
| Intraday bars (tất cả intervals) | ~35 GB |
| Tick data | ~125 GB |
| OHLCV ngày + Finance + Company | ~5 GB |
| **Tổng** | **~165 GB/năm** |

---

## 10. Công Cụ Backfill — Chạy Thủ Công

File `backfill.py` cho phép chạy thủ công từng job với date range tùy chọn.

```bash
# Kích hoạt venv trước
cd data-pipeline
source venv/bin/activate  # Linux/Mac
# hoặc
venv\Scripts\activate     # Windows

# OHLCV cho 3 symbols trong 1 tuần
python backfill.py ohlcv --start 2025-03-01 --end 2025-03-07 --symbols VIC VHM ACB

# OHLCV tất cả symbols từ đầu năm đến nay
python backfill.py ohlcv --start 2025-01-01

# Giao dịch khối ngoại
python backfill.py foreign-flow --start 2025-03-01 --end 2025-03-10 --symbols VIC VHM

# Đồng bộ danh sách mã (không cần date)
python backfill.py listing

# Thông tin công ty cho 1 số mã
python backfill.py company --symbols VIC VHM ACB

# Báo cáo tài chính
python backfill.py finance --symbols VIC
```

**Subcommands:**

| Lệnh | Tham số | Mô tả |
|---|---|---|
| `ohlcv` | `--start` (bắt buộc), `--end`, `--symbols` | Fetch OHLCV daily |
| `foreign-flow` | `--start` (bắt buộc), `--end`, `--symbols` | Fetch giao dịch khối ngoại |
| `listing` | _(không có)_ | Sync danh sách mã + ICB |
| `company` | `--symbols` | Fetch thông tin công ty |
| `finance` | `--symbols` | Fetch báo cáo tài chính |

---

## Tóm Tắt Nhanh — Sơ đồ Tổng Thể

```
vnstock API (VCI)
       │
       ▼
┌─────────────────────────────────────────────┐
│              DATA PIPELINE                  │
│                                             │
│  scheduler.py (APScheduler)                 │
│  ├─ Mon 07:00 → job_sync_listing            │
│  ├─ Mon-Fri 17:30 → job_fetch_ohlcv_daily  │
│  ├─ Mon 08:00 → job_fetch_company_profiles  │
│  ├─ 1st/month 09:00 → job_fetch_finance     │
│  └─ Mon-Fri 17:45 → job_fetch_foreign_flow  │
│                                             │
│  Mỗi job = Extract → Transform → Load       │
└─────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│         PostgreSQL 16 (stockapp)            │
│                                             │
│  listing.*    → Danh mục mã CK, ICB         │
│  market.*     → Giá OHLCV, tick, index      │
│  company.*    → Hồ sơ công ty               │
│  finance.*    → BCTC (EAV)                  │
│  trading.*    → Khối ngoại, thỏa thuận      │
│  derivatives.*→ Futures, CW                 │
│  index_data.* → Chỉ số, thành phần          │
│  fund.*       → Quỹ đầu tư, NAV             │
│  macro.*      → Tỷ giá, GDP, CPI...         │
│  commodity.*  → Vàng, xăng, thép...         │
│  etl.*        → Tracking jobs, freshness    │
└─────────────────────────────────────────────┘
```
