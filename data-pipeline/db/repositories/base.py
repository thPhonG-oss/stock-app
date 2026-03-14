from sqlalchemy import Connection
from loguru import logger


class BaseRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.logger = logger
