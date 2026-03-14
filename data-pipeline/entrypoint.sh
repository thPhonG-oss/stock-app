#!/bin/bash
set -e  # Dừng ngay nếu có lệnh nào fail

echo "================================================"
echo "  Stock Pipeline — Starting"
echo "================================================"

# ── Bước 1: Cài vnstock sponsor package nếu có API key ───
INSTALLER_FLAG="/app/.vnstock_installed"

if [ -z "$VNSTOCK_API_KEY" ]; then
    echo "⚠️  VNSTOCK_API_KEY not set — running with base vnstock only"
else
    # Chỉ chạy installer một lần duy nhất
    # Flag file đảm bảo restart container không cài lại
    if [ ! -f "$INSTALLER_FLAG" ]; then
        echo "✓ Installing vnstock sponsor packages..."
        /app/vnstock-cli-installer.run -- --api-key "$VNSTOCK_API_KEY"
        touch "$INSTALLER_FLAG"
        echo "✓ Sponsor packages installed"
    else
        echo "✓ Sponsor packages already installed — skipping"
    fi
fi

# ── Bước 2: Kiểm tra kết nối PostgreSQL ──────────────────
echo "⏳ Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
until python3 -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
    echo "  PostgreSQL not ready — retrying in 3s..."
    sleep 3
done
echo "✅ PostgreSQL is ready"

# ── Bước 3: Kiểm tra kết nối Redis ───────────────────────
echo "⏳ Waiting for Redis at $REDIS_HOST:$REDIS_PORT..."
until python3 -c "
import redis, os, sys
try:
    r = redis.Redis(
        host=os.environ.get('REDIS_HOST', 'localhost'),
        port=int(os.environ.get('REDIS_PORT', 6379)),
    )
    r.ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
    echo "  Redis not ready — retrying in 3s..."
    sleep 3
done
echo "✅ Redis is ready"

# ── Bước 4: Chạy pipeline ─────────────────────────────────
echo "🚀 Starting scheduler..."
exec python3 scheduler.py