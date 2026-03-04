from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.core.exceptions import DatabaseError, RecallError


class Base(DeclarativeBase):
    pass


def create_async_engine_from_settings() -> AsyncEngine:
    """Create async SQLAlchemy engine from settings."""
    try:
        # Ensure parent directory exists
        db_path = Path(settings.sqlite_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        sqlite_url = f"sqlite+aiosqlite:///{db_path}"
        return create_async_engine(
            sqlite_url,
            echo=False,  # Set to True for SQL debugging
            future=True,
        )
    except RecallError:
        raise
    except Exception as e:
        raise DatabaseError(detail=str(e)) from e


# Private engine and session factory for lazy initialization
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        try:
            _engine = create_async_engine_from_settings()
        except RecallError:
            raise
        except Exception as e:
            raise DatabaseError(detail=str(e)) from e
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def dispose_engine() -> None:
    """Dispose the engine and reset internal state.
    
    This should be called during application shutdown.
    """
    global _engine, _session_factory
    if _engine is not None:
        try:
            await _engine.dispose()
        except RecallError:
            raise
        except Exception as e:
            raise DatabaseError(detail=str(e)) from e
        finally:
            _engine = None
            _session_factory = None


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions.
    
    Usage:
        async with get_async_session() as session:
            await session.execute(...)
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            raise DatabaseError(detail=str(e)) from e
        except Exception as e:
            await session.rollback()
            raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency-compatible session generator.
    
    Usage in FastAPI:
        @app.get("/")
        async def endpoint(session: AsyncSession = Depends(get_session)):
            ...
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            raise DatabaseError(detail=str(e)) from e
        except Exception as e:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create all tables defined in Base metadata.
    
    This should be called once during application startup.
    """
    try:
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except RecallError:
        raise
    except Exception as e:
        raise DatabaseError(detail=str(e)) from e


async def drop_tables() -> None:
    """Drop all tables (for testing/development only)."""
    try:
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except RecallError:
        raise
    except Exception as e:
        raise DatabaseError(detail=str(e)) from e
