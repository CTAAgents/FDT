import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PGConfig:
    def __init__(self):
        self.host = os.environ.get("PG_HOST", "localhost")
        self.port = int(os.environ.get("PG_PORT", "5432"))
        self.database = os.environ.get("PG_DATABASE", "fdt")
        self.username = os.environ.get("PG_USERNAME", "fdt_user")
        self.password = os.environ.get("PG_PASSWORD", "")
        self.schema = os.environ.get("PG_SCHEMA", "public")
        self.pool_max = int(os.environ.get("PG_POOL_MAX", "10"))
        self.pool_min = int(os.environ.get("PG_POOL_MIN", "2"))
        self.pool_timeout = int(os.environ.get("PG_POOL_TIMEOUT", "30"))
        self.pool_recycle = int(os.environ.get("PG_POOL_RECYCLE", "3600"))

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+psycopg2://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


class PGConnection:
    _engine = None
    _session_factory = None

    @classmethod
    def initialize(cls):
        config = PGConfig()
        cls._engine = create_engine(
            config.dsn,
            poolclass=QueuePool,
            pool_size=config.pool_min,
            max_overflow=config.pool_max - config.pool_min,
            pool_timeout=config.pool_timeout,
            pool_recycle=config.pool_recycle,
            echo=False,
        )
        cls._session_factory = scoped_session(
            sessionmaker(bind=cls._engine, autoflush=True)
        )
        logger.info(f"PostgreSQL connection initialized: {config.host}:{config.port}/{config.database}")

    @classmethod
    def get_engine(cls):
        if cls._engine is None:
            cls.initialize()
        return cls._engine

    @classmethod
    def get_session(cls):
        if cls._session_factory is None:
            cls.initialize()
        return cls._session_factory()

    @classmethod
    @contextmanager
    def session_scope(cls):
        session = cls.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    @classmethod
    def health_check(cls) -> bool:
        try:
            engine = cls.get_engine()
            with engine.connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"PostgreSQL health check failed: {e}")
            return False