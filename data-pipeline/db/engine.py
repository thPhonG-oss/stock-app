from sqlalchemy import create_engine, Engine, text
from sqlalchemy.pool import QueuePool
from loguru import logger

from config.settings import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.db_url,
            poolclass=QueuePool,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            echo=False,
        )
        safe_url = settings.db_url.split("@", 1)[-1]
        logger.info("Database engine created → {}", safe_url)
    return _engine


def get_connection():
    return get_engine().connect()


def check_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("DB connection failed: {}", exc)
        return False
