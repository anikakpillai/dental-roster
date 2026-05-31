"""
Database connection management.

This is the ONLY file that knows how to reach MySQL. Everything else
in the app asks this module for a connection — they never hardcode
credentials or connection logic themselves.
"""
from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Local dev connection. When pointing at a real Open Dental server,
# only this string changes — no other code needs to change.
DB_USER = "root"
DB_PASSWORD = "rootpass"
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_NAME = "opendental_dev"

_CONNECTION_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# A single shared engine. SQLAlchemy manages a pool of connections
# behind this object so we don't open/close a raw connection every query.
_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(_CONNECTION_URL, pool_pre_ping=True)
    return _engine
