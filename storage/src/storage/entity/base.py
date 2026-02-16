from sqlalchemy import Column, String, BigInteger
from sqlalchemy.orm import DeclarativeBase
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp


class Base(DeclarativeBase):
    pass


class BaseEntity:
    created_at = Column(String, default=get_utc_iso8601_timestamp)
    updated_at = Column(String, default=get_utc_iso8601_timestamp, onupdate=get_utc_iso8601_timestamp)
    created_at_unix = Column(BigInteger, default=get_unix_timestamp)
    updated_at_unix = Column(BigInteger, default=get_unix_timestamp, onupdate=get_unix_timestamp)
