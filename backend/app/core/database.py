from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def create_async_engine_from_settings() -> AsyncEngine:
    """Create async SQLAlchemy engine from settings."""
    # Ensure parent directory exists
    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sqlite_url = f"sqlite+aiosqlite:///{db_path}"
    return create_async_engine(
        sqlite_url,
        echo=False,  # Set to True for SQL debugging
        future=True,
    )


# Global engine and session factory
engine: AsyncEngine = create_async_engine_from_settings()
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions.
    
    Usage:
        async with get_async_session() as session:
            await session.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    """Create all tables defined in Base metadata.
    
    This should be called once during application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Drop all tables (for testing/development only)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
