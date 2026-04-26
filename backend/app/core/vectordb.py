"""
Qdrant vector database service wrapper.

This module provides the QdrantService class as the sole entry point for Qdrant operations.
All Qdrant SDK exceptions are converted to project-specific exceptions.
"""

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import (
    UnexpectedResponse,
)
from qdrant_client.models import (
    CollectionInfo,
    Distance,
    Filter,
    PointIdsList,
    PointStruct,
    Record,
    ScoredPoint,
    SearchRequest,
)

from app.config import settings
from app.core.exceptions import (
    CollectionNotFoundError,
    EmbeddingDimensionMismatchError,
    VectorDBError,
)

logger = logging.getLogger(__name__)


class QdrantService:
    """Qdrant vector database service wrapper.

    Serves as the sole entry point for Qdrant operations, shielding upper layers from SDK details.
    Lifecycle managed by FastAPI lifespan.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection_name: str | None = None,
    ) -> None:
        """Initialize Qdrant service with configuration.

        Args:
            host: Qdrant host, defaults to settings.qdrant_host
            port: Qdrant port, defaults to settings.qdrant_port
            collection_name: Collection name, defaults to settings.qdrant_collection
        """
        self.host = host or settings.qdrant_host
        self.port = port or settings.qdrant_port
        self.collection_name = collection_name or settings.qdrant_collection
        self.client: AsyncQdrantClient | None = None

    async def __aenter__(self) -> "QdrantService":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def connect(self) -> None:
        """Establish connection to Qdrant."""
        if self.client is not None:
            return
        try:
            self.client = AsyncQdrantClient(host=self.host, port=self.port)
            logger.info(f"Connected to Qdrant at {self.host}:{self.port}")
        except Exception as e:
            raise VectorDBError(f"Failed to connect to Qdrant: {e}") from e

    async def close(self) -> None:
        """Close Qdrant connection."""
        if self.client:
            await self.client.close()
            logger.debug("Qdrant connection closed")

    def _ensure_connected(self) -> None:
        """Ensure client is connected."""
        if self.client is None:
            raise VectorDBError("Qdrant client not connected. Call connect() first.")

    # --------------------------------------------------------------------
    # 1. Collection Management
    # --------------------------------------------------------------------

    async def ensure_collection(
        self,
        dimension: int,
        distance: Distance = Distance.COSINE,
    ) -> None:
        """Ensure collection exists with given configuration.

        Idempotent operation: skip if collection exists with matching config.
        Raises EmbeddingDimensionMismatchError if existing collection dimension mismatches.

        Args:
            dimension: Vector dimension
            distance: Distance metric, defaults to COSINE

        Raises:
            VectorDBError: Qdrant operation failed
            EmbeddingDimensionMismatchError: Existing collection dimension mismatches
        """
        self._ensure_connected()
        try:
            collections = await self.client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={
                        "size": dimension,
                        "distance": distance,
                    },
                )
                logger.info(
                    f"Created collection '{self.collection_name}' "
                    f"with dimension {dimension}"
                )
                return

            # Collection exists, verify dimension
            info = await self.client.get_collection(self.collection_name)
            existing_dim = info.config.params.vectors.size
            if existing_dim != dimension:
                raise EmbeddingDimensionMismatchError(
                    expected=dimension,
                    actual=existing_dim,
                    detail=(
                        f"Collection '{self.collection_name}' "
                        f"dimension mismatch: {existing_dim} vs {dimension}"
                    ),
                )
            logger.debug(
                f"Collection '{self.collection_name}' already exists "
                f"with dimension {dimension}"
            )

        except EmbeddingDimensionMismatchError:
            raise
        except Exception as e:
            raise VectorDBError(f"Failed to ensure collection: {e}") from e

    async def delete_collection(self) -> None:
        """Delete entire collection.

        Used for reindex scenarios where complete rebuild is cleaner than piecewise deletion.

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        try:
            await self.client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection '{self.collection_name}'")
        except Exception as e:
            raise VectorDBError(f"Failed to delete collection: {e}") from e

    async def get_collection_info(self) -> CollectionInfo | None:
        """Get collection metadata.

        Returns:
            CollectionInfo if collection exists, None otherwise

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        try:
            return await self.client.get_collection(self.collection_name)
        except CollectionNotFoundError:
            return None
        except UnexpectedResponse as e:
            raise VectorDBError(f"Collection does not exist: {self.collection_name}") from e
        except Exception as e:
            raise VectorDBError(f"Failed to get collection info: {e}") from e

    # --------------------------------------------------------------------
    # 2. Data Writing
    # --------------------------------------------------------------------

    async def upsert(self, points: list[PointStruct]) -> None:
        """Batch upsert points.

        Idempotent: points with same ID are overwritten.
        Internal batch slicing to avoid oversized single requests.
        Empty list returns immediately.

        Recommended payload structure (constructed by chunk_manager):
            {
                "document_id": str,      # Parent document UUID
                "chunk_index": int,      # Chunk index within document
                "tags": list[str],       # Tag list for metadata filter and reranker
                "created_at": str,       # ISO format timestamp
            }

        Args:
            points: List of PointStruct to upsert

        Raises:
            VectorDBError: Qdrant operation failed
        """
        if not points:
            return

        self._ensure_connected()
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            try:
                await self.client.upsert(
                    collection_name=self.collection_name,
                    points=batch,
                )
                logger.debug(f"Upserted {len(batch)} points to '{self.collection_name}'")
            except Exception as e:
                raise VectorDBError(f"Failed to upsert batch {i//batch_size}: {e}") from e

        logger.info(f"Upserted total {len(points)} points to '{self.collection_name}'")

    async def delete(self, point_ids: list[str]) -> None:
        """Batch delete points by IDs.

        Empty list returns immediately.

        Args:
            point_ids: List of point IDs to delete

        Raises:
            VectorDBError: Qdrant operation failed
        """
        if not point_ids:
            return

        self._ensure_connected()
        batch_size = 100
        for i in range(0, len(point_ids), batch_size):
            batch = point_ids[i:i + batch_size]
            try:
                await self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=batch),
                )
                logger.debug(f"Deleted {len(batch)} points from '{self.collection_name}'")
            except Exception as e:
                raise VectorDBError(f"Failed to delete batch {i//batch_size}: {e}") from e

        logger.info(f"Deleted total {len(point_ids)} points from '{self.collection_name}'")

    # --------------------------------------------------------------------
    # 3. Retrieval
    # --------------------------------------------------------------------

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        score_threshold: float | None = None,
        query_filter: Filter | None = None,
    ) -> list[ScoredPoint]:
        """ANN search with single query.

        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return, defaults to 10
            score_threshold: Minimum similarity score, defaults to None
            query_filter: Metadata filter, defaults to None

        Returns:
            List of ScoredPoint containing id, score, and payload

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        try:
            return await self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=query_filter,
            )
        except Exception as e:
            raise VectorDBError(f"Failed to search: {e}") from e

    async def search_batch(self, queries: list[SearchRequest]) -> list[list[ScoredPoint]]:
        """Batch ANN search.

        Single RPC with multiple queries, used for RAG-Fusion scenarios.

        Args:
            queries: List of SearchRequest objects

        Returns:
            List of search results for each query

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        try:
            return await self.client.search_batch(
                collection_name=self.collection_name,
                requests=queries,
            )
        except Exception as e:
            raise VectorDBError(f"Failed to search batch: {e}") from e

    # --------------------------------------------------------------------
    # 4. Consistency Maintenance
    # --------------------------------------------------------------------

    async def get_points(
        self,
        point_ids: list[str],
        with_payload: bool = True,
        with_vectors: bool = False,
    ) -> list[Record]:
        """Retrieve points by IDs.

        Used by chunk_manager to verify synced chunks exist in Qdrant.

        Args:
            point_ids: List of point IDs to retrieve
            with_payload: Include payload in response, defaults to True
            with_vectors: Include vectors in response, defaults to False

        Returns:
            List of Record objects

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        try:
            return await self.client.retrieve(
                collection_name=self.collection_name,
                ids=point_ids,
                with_payload=with_payload,
                with_vectors=with_vectors,
            )
        except Exception as e:
            raise VectorDBError(f"Failed to get points: {e}") from e

    async def count(self) -> int:
        """Get total point count in collection.

        Used for quick comparison between SQLite and Qdrant.

        Returns:
            Number of points in collection

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        try:
            info = await self.client.get_collection(self.collection_name)
            return info.points_count
        except Exception as e:
            raise VectorDBError(f"Failed to count points: {e}") from e

    async def count_by_filter(
            self,
            count_filter: Filter,
    ) -> int:
        """按条件统计 point 数量。

        用于 Layer 1 健康检查：按 doc_id 过滤后与 SQLite 侧 chunk 数量比较。

        Args:
            count_filter: Qdrant Filter 条件

        Returns:
            满足条件的 point 数量

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        try:
            result = await self.client.count(
                collection_name=self.collection_name,
                count_filter=count_filter,
                exact=True,  # 精确计数，不用近似值
            )
            return result.count
        except Exception as e:
            raise VectorDBError(f"Failed to count points: {e}") from e

    async def set_payload_for_points(
        self,
        payload: dict,
        point_ids: list[str],
    ) -> None:
        """Overwrite specific payload fields for a list of points.

        Does not touch payload fields not present in `payload`.
        Empty list returns immediately.

        Args:
            payload: Fields to set (e.g. {"tags": ["ml", "rag"]})
            point_ids: Point UUIDs to update

        Raises:
            VectorDBError: Qdrant operation failed
        """
        if not point_ids:
            return
        self._ensure_connected()
        batch_size = 100
        for i in range(0, len(point_ids), batch_size):
            batch = point_ids[i : i + batch_size]
            try:
                await self.client.set_payload(
                    collection_name=self.collection_name,
                    payload=payload,
                    points=batch,
                )
                logger.debug("Set payload for %d points", len(batch))
            except Exception as e:
                raise VectorDBError(
                    f"Failed to set payload for batch {i // batch_size}: {e}"
                ) from e
        logger.info("Set payload for total %d points", len(point_ids))

    async def scroll_ids(
            self,
            scroll_filter: Filter,
            batch_size: int = 100,
    ) -> set[str]:
        """按条件遍历所有 point，只收集 ID。

        用于 Layer 2 健康检查：取出某 doc_id 下所有 point_id，
        与 SQLite 侧 chunk_id 集合做双向差集。

        不取 payload 和 vector，最小化传输量。

        Args:
            scroll_filter: Qdrant Filter 条件
            batch_size: 单次 scroll 返回上限，默认 100

        Returns:
            满足条件的所有 point_id 集合

        Raises:
            VectorDBError: Qdrant operation failed
        """
        self._ensure_connected()
        all_ids: set[str] = set()
        next_offset = None

        try:
            while True:
                points, next_offset = await self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=scroll_filter,
                    limit=batch_size,
                    offset=next_offset,
                    with_payload=False,
                    with_vectors=False,
                )
                all_ids.update(str(p.id) for p in points)

                if next_offset is None:
                    break

            return all_ids

        except Exception as e:
            raise VectorDBError(f"Failed to scroll points: {e}") from e
