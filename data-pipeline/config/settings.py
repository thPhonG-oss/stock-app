from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "stockapp"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"

    # Connection pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Vnstock
    VNSTOCK_SOURCE: str = "VCI"
    VNSTOCK_API_KEY: str = ""

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # Pipeline behaviour
    BOOTSTRAP_LOOKBACK_DAYS: int = 1095  # default 3 years
    BATCH_SIZE: int = 50                  # symbols per fetch batch
    INTRADAY_PAGE_SIZE: int = 100

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"


settings = Settings()
