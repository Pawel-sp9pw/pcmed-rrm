from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings


@lru_cache
def session_factory():
    return sessionmaker(create_engine(settings().database_url, pool_pre_ping=True), expire_on_commit=False)


def database():
    with session_factory()() as session:
        yield session
