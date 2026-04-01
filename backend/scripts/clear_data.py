"""Clear all data from Qdrant and delete the SQLite database."""
import asyncio
import os
import sys

from qdrant_client import AsyncQdrantClient


async def clear_qdrant(host: str = "localhost", port: int = 6333, collection: str = "recall") -> None:
    client = AsyncQdrantClient(host=host, port=port)
    try:
        collections = await client.get_collections()
        names = [c.name for c in collections.collections]
        print(f"Qdrant collections found: {names}")
        if collection in names:
            await client.delete_collection(collection)
            print(f"Deleted Qdrant collection '{collection}'")
        else:
            print(f"Collection '{collection}' not found, skipping")
    finally:
        await client.close()


def clear_sqlite(db_path: str) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Deleted SQLite database: {db_path}")
    else:
        print(f"SQLite database not found at {db_path}, skipping")


if __name__ == "__main__":
    # Resolve db path relative to backend/
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(backend_dir, "data", "recall.db")

    asyncio.run(clear_qdrant())
    clear_sqlite(db_path)
    print("Done.")
