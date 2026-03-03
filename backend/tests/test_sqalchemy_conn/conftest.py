import asyncio
import importlib
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Create a temporary SQLite database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    yield db_path
    # Clean up after tests
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def test_model(database_module):
    """Define a simple test model for table creation verification."""
    import uuid

    from sqlalchemy import String
    from sqlalchemy.orm import Mapped, mapped_column

    # Generate unique table name to avoid metadata conflicts
    table_name = f"test_documents_{uuid.uuid4().hex[:8]}"

    # Create class dictionary with proper SQLAlchemy 2.0 style
    class_dict = {
        "__tablename__": table_name,
        "__annotations__": {
            "id": Mapped[int],
            "name": Mapped[str],
        },
        "id": mapped_column(primary_key=True),
        "name": mapped_column(String(100)),
    }

    # Create model class dynamically using Base from the reloaded module
    TestModel = type(table_name, (database_module.Base,), class_dict)

    return TestModel


@pytest.fixture
def database_module(monkeypatch, temp_db_path):
    """Reload database module with temporary database path."""
    # Set environment variable before importing/reloading
    monkeypatch.setenv("SQLITE_PATH", temp_db_path)

    # Reload the database module to pick up new environment variable
    import app.core.database
    importlib.reload(app.core.database)

    # Clear existing metadata to avoid table conflicts
    app.core.database.Base.metadata.clear()

    return app.core.database


@pytest.fixture
async def async_session(database_module) -> AsyncGenerator[AsyncSession, None]:
    """Create an async session for testing."""
    async with database_module.get_async_session() as session:
        yield session


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
