from pathlib import Path

from sqlalchemy import text
from loguru import logger

from db.engine import get_engine

SCHEMA_PATH = Path(__file__).parent / "scripts" / "schema.sql"


def schema_exists() -> bool:
    """Return True if the sentinel table listing.symbol already exists."""
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'listing' AND table_name = 'symbol' LIMIT 1"
                )
            ).fetchone()
        return row is not None
    except Exception:
        return False


def init_schema() -> None:
    """Execute schema.sql once; skip if already initialised."""
    if schema_exists():
        logger.info("Schema already initialised — skipping DDL.")
        return

    logger.info("Initialising database schema from {}", SCHEMA_PATH)
    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with get_engine().connect() as conn:
        conn.execute(text(sql))
        conn.commit()

    logger.success("Schema initialised successfully.")
