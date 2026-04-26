import asyncio

from sqlalchemy import text

from app.core.database import get_engine


async def run():
    async with get_engine().begin() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM chunks_context_fts"))
        before = result.scalar()
        await conn.execute(text("DELETE FROM chunks_context_fts"))
        print(f"Cleared {before} rows from chunks_context_fts.")

asyncio.run(run())
