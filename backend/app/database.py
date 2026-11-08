import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_database_url, load_environment

# Ensure environment variables are loaded
load_environment()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL must be configured. "
            "Please ensure backend/.env contains a valid DATABASE_URL "
            "(e.g., postgresql+psycopg://postgres:password@localhost:5432/orderflow) "
            "or set the DATABASE_URL environment variable."
        )

    return create_engine(database_url, pool_pre_ping=True)


def get_db_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
