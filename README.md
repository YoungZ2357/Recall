# Recall
Recall is a personal-use local knowledge base retrieval service. It focuses on high-quality document retrieval, 
multi-dimensional reordering, and post-retrieval contextual refinement, rather than end-to-end generation.


## Architecture
```
Query → Query Transform → Vector Recall → Reranking → Refinement → Return Context
             │                 │              │             │
        query_transform     searcher       reranker      refiner/
        ├ RAG-Fusion        Qdrant ANN     ├ Weighted scoring        ├ deduplicator (planned)
        ├ HyDE              + RRF merge    ├ Metadata score          ├ context_compressor (planned)
        └ Query rewriting                  ├ Ebbinghaus retention    └ summarizer (planned)
                                           ├ Cross-Encoder (planned)
                                           └ Graph signals (planned)
```

## Tech Stack

| Layer          | Technology                                                  |
|----------------|-------------------------------------------------------------|
| Backend        | Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · aiosqlite |
| Vector DB      | Qdrant (Docker)                                             |
| Embedding      | GLM Embedding-3 (online) · BGE + ONNX Runtime (offline)     |
| Frontend       | React · TypeScript · Vite · Ant Design                      |
| AI Integration | MCP (stdio / SSE dual-mode)                                 |


## Project Structure

```
Recall/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/                    # HTTP routes (planned)
│   │   ├── cli/                    # CLI entrypoints
│   │   │   ├── __main__.py         #   `python -m app.cli`
│   │   │   ├── ingest.py           #   ingest command
│   │   │   ├── reindex.py          #   reindex command
│   │   │   └── _init_deps.py       #   dependency wiring
│   │   ├── ingestion/              # Document ingestion
│   │   │   ├── pipeline.py         #   end-to-end ingestion orchestration
│   │   │   ├── parser.py           #   format dispatcher
│   │   │   ├── parsers/
│   │   │   │   ├── text.py         #   plain text
│   │   │   │   └── pdf.py          #   PDF via Marker CLI
│   │   │   ├── chunker.py          #   RecursiveSplit / FixedCount strategies
│   │   │   └── embedder.py         #   BaseEmbedder + APIEmbedder (GLM)
│   │   ├── retrieval/              # Retrieval core
│   │   │   ├── searcher.py         #   VectorSearcher (Qdrant ANN) + RRF merge
│   │   │   ├── reranker.py         #   weighted scoring + Ebbinghaus retention
│   │   │   └── query_transform.py  #   query rewriting stubs (planned)
│   │   ├── refiner/                # Post-retrieval refinement (planned)
│   │   ├── generation/             # Minimal generation (planned)
│   │   ├── mcp/                    # MCP service (planned)
│   │   └── core/                   # Shared infrastructure
│   │       ├── database.py         #   SQLAlchemy async engine + session factory
│   │       ├── models.py           #   ORM models (Document, Chunk, AccessLog)
│   │       ├── schemas.py          #   Pydantic request/response models
│   │       ├── vectordb.py         #   Qdrant async client wrapper
│   │       ├── chunk_manager.py    #   SQLite ↔ Qdrant dual-write lifecycle
│   │       ├── repository.py       #   Document / Chunk data access layer
│   │       └── exceptions.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/                       # React + TypeScript (planned)
├── docker-compose.yml
└── CLAUDE.md
```