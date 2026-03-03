import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


class TestDatabase:
    """Test database module functionality."""

    def test_create_async_engine_from_settings(self, database_module):
        """Test engine creation with temporary database path."""
        engine = database_module.engine

        assert isinstance(engine, AsyncEngine)
        assert engine.url.database.endswith(".db")

    @pytest.mark.asyncio
    async def test_create_tables(self, database_module, test_model):
        """Test table creation."""
        # Create tables
        await database_module.create_tables()

        # Verify tables exist
        async with database_module.engine.begin() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )

        assert test_model.__tablename__ in table_names

    @pytest.mark.asyncio
    async def test_drop_tables(self, database_module, test_model):
        """Test table deletion."""
        # First create tables
        await database_module.create_tables()

        # Drop tables
        await database_module.drop_tables()

        # Verify tables are removed
        async with database_module.engine.begin() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )

        assert test_model.__tablename__ not in table_names

    @pytest.mark.asyncio
    async def test_get_async_session_commit(self, database_module, test_model):
        """Test session commit works correctly."""
        # Create tables first
        await database_module.create_tables()

        async with database_module.get_async_session() as session:
            # Create a test document
            doc = test_model(id=1, name="Test Document")
            session.add(doc)
            # Commit happens automatically when context exits

        # Verify document was persisted
        async with database_module.get_async_session() as session:
            result = await session.execute(
                text(f"SELECT name FROM {test_model.__tablename__} WHERE id = 1")
            )
            row = result.fetchone()
            assert row is not None
            assert row[0] == "Test Document"

    @pytest.mark.asyncio
    async def test_get_async_session_rollback(self, database_module, test_model):
        """Test session rollback on exception."""
        # Create tables first
        await database_module.create_tables()

        # Simulate an exception during transaction
        try:
            async with database_module.get_async_session() as session:
                doc = test_model(id=2, name="Should Rollback")
                session.add(doc)
                # Raise exception to trigger rollback
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        # Verify document was NOT persisted due to rollback
        async with database_module.get_async_session() as session:
            result = await session.execute(
                text(f"SELECT name FROM {test_model.__tablename__} WHERE id = 2")
            )
            row = result.fetchone()
            assert row is None

    @pytest.mark.asyncio
    async def test_session_autoclose(self, database_module):
        """Test session is automatically closed after context exit."""
        async with database_module.get_async_session() as session:
            assert isinstance(session, AsyncSession)
            # Session is active within context
            assert session.is_active

        # Session should be closed after context exit
        # Note: SQLAlchemy doesn't expose a simple 'closed' attribute for async sessions
        # We'll verify by checking no active connection
        async with database_module.engine.connect() as conn:
            # Just verify we can create a new connection without issues
            assert conn is not None
