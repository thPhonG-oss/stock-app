# ─────────────────────────────────────────────────────────────────
#  Stock Pipeline — Dockerfile
#  Kết hợp: vnstock official installer + pipeline dependencies
# ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# ── System dependencies ───────────────────────────────────────────
# build-essential + wget : yêu cầu của vnstock installer
# libpq-dev              : yêu cầu của psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    curl \
    ca-certificates \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Virtual environment ───────────────────────────────────────────
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── Vnstock environment flags ─────────────────────────────────────
ENV VNSTOCK_LANGUAGE=2 \
    VNSTOCK_INTERACTIVE=0 \
    PYTHONUNBUFFERED=1

# ── Bước 1: Cài vnstock base + các dependency của nó ─────────────
# Tách layer này riêng để Docker cache — chỉ rebuild khi vnstock update
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
    "vnstock>=3.3.0" \
    "vnai>=2.2.3" \
    "requests>=2.31.0" \
    "numpy>=1.26.4" \
    "pandas>=1.5.3" \
    "beautifulsoup4>=4.9.3" \
    "aiohttp>=3.11.3" \
    "nest-asyncio>=1.6.0" \
    "pydantic>=2.0.0" \
    "psutil>=5.9.0" \
    "pyarrow>=14.0.1" \
    "openpyxl>=3.0.0" \
    "tqdm>=4.67.0" \
    "duckdb>=1.2.0"

# Cài thêm từ vnstock private index (vnii và sponsor packages base)
RUN pip install --no-cache-dir \
    --extra-index-url https://vnstocks.com/api/simple \
    vnii || echo "⚠️  vnii not available without API key — skipping"

# ── Bước 2: Download vnstock installer (cho sponsor packages) ─────
# Installer được download tại build time, chạy tại runtime
RUN wget -q https://vnstocks.com/files/vnstock-cli-installer.run \
    -O /app/vnstock-cli-installer.run && \
    chmod +x /app/vnstock-cli-installer.run

# ── Bước 3: Cài pipeline dependencies ────────────────────────────
# Layer riêng — rebuild khi requirements.txt thay đổi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Bước 4: Copy source code ──────────────────────────────────────
COPY . .

# ── Setup ─────────────────────────────────────────────────────────
RUN mkdir -p logs && \
    chmod +x entrypoint.sh

# ── Health check ──────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import vnstock; from apscheduler.schedulers.blocking import BlockingScheduler; print('OK')" || exit 1

ENTRYPOINT ["./entrypoint.sh"]