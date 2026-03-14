"""
sources/vnstock_source.py

Singleton wrapper quản lý tất cả vnstock client instances.
Chỉ tạo client 1 lần, tái sử dụng cho toàn bộ pipeline.
"""

from loguru import logger
from config.settings import settings


class VnstockSource:
    """
    Factory / cache cho các vnstock API clients.
    Sử dụng class-level cache để đảm bảo mỗi client chỉ khởi tạo 1 lần.
    """

    _listing = None
    _quote = None
    _company_cache: dict = {}
    _finance_cache: dict = {}
    _trading_cache: dict = {}

    # ── Listing (không cần symbol) ────────────────────────────────────
    @classmethod
    def listing(cls):
        """Trả về Listing client (singleton)."""
        if cls._listing is None:
            from vnstock import Listing
            src = settings.VNSTOCK_SOURCE
            cls._listing = Listing(source=src)
            logger.info("Khởi tạo Listing client (source={})", src)
        return cls._listing

    # ── Quote (cần symbol) ────────────────────────────────────────────
    @classmethod
    def quote(cls, symbol: str = ""):
        """
        Trả về Quote client.
        Quote hỗ trợ truyền symbol trực tiếp trong method call,
        nên ta dùng 1 instance chung.
        """
        if cls._quote is None:
            from vnstock import Quote
            src = settings.VNSTOCK_SOURCE
            cls._quote = Quote(source=src, symbol=symbol)
            logger.info("Khởi tạo Quote client (source={})", src)
        return cls._quote

    # ── Company (cần symbol khi init) ─────────────────────────────────
    @classmethod
    def company(cls, symbol: str):
        """Trả về Company client cho symbol (cached)."""
        key = symbol.upper()
        if key not in cls._company_cache:
            from vnstock import Company
            src = settings.VNSTOCK_SOURCE
            cls._company_cache[key] = Company(source=src, symbol=key)
            logger.debug("Khởi tạo Company client ({}, source={})", key, src)
        return cls._company_cache[key]

    # ── Finance (cần symbol khi init) ─────────────────────────────────
    @classmethod
    def finance(cls, symbol: str, period: str = "quarter"):
        """Trả về Finance client cho symbol (cached theo symbol+period)."""
        key = f"{symbol.upper()}_{period}"
        if key not in cls._finance_cache:
            from vnstock import Finance
            src = settings.VNSTOCK_SOURCE
            cls._finance_cache[key] = Finance(
                source=src, symbol=symbol.upper(),
                period=period, get_all=True,
            )
            logger.debug("Khởi tạo Finance client ({}, period={}, source={})", symbol, period, src)
        return cls._finance_cache[key]

    # ── Trading (cần symbol khi init) ─────────────────────────────────
    @classmethod
    def trading(cls, symbol: str):
        """Trả về Trading client cho symbol (cached)."""
        key = symbol.upper()
        if key not in cls._trading_cache:
            from vnstock import Trading
            src = settings.VNSTOCK_SOURCE
            cls._trading_cache[key] = Trading(source=src, symbol=key)
            logger.debug("Khởi tạo Trading client ({}, source={})", key, src)
        return cls._trading_cache[key]

    # ── Tiện ích ──────────────────────────────────────────────────────
    @classmethod
    def clear_cache(cls):
        """Xoá toàn bộ cache (dùng khi cần reset)."""
        cls._listing = None
        cls._quote = None
        cls._company_cache.clear()
        cls._finance_cache.clear()
        cls._trading_cache.clear()
        logger.info("Đã xoá toàn bộ vnstock client cache")
