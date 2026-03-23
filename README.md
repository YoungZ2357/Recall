# Recall
Recall is a personal-use local knowledge base retrieval service. It emphasizes retrieval quality over generation — combining query transformation (RAG-Fusion, HyDE), multi-signal reranking (tag-semantic scoring, Ebbinghaus memory decay), and post-retrieval refinement (deduplication, context compression, summarization), exposed via REST API and MCP.


## Architecture

**Implemented**
```
Ingestion:  File → Parser → Chunker → Embedder → SQLite + Qdrant

Retrieval:  Query → VectorSearcher → RRF merge → Reranker → Return Context
                         │                            │
                     Qdrant ANN                 ├ Weighted scoring (α·retrieval + β·metadata + γ·retention)
                     score threshold            ├ Tag semantic score (Max-Pooling cosine · doc weight)
                                                └ Ebbinghaus retention (access frequency + recency)
```

**Planned**
```
Query → Query Transform → Retrieval → Reranking → Refinement → API / MCP
         ├ RAG-Fusion                               ├ Deduplicator
         ├ HyDE                                     ├ Context compressor
         └ Query rewriting                          └ Summarizer
```

## Tech Stack

| Layer          | Technology                                                  |
|----------------|-------------------------------------------------------------|
| Backend        | Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · aiosqlite |
| Vector DB      | Qdrant (Docker)                                             |
| Embedding      | GLM Embedding-3 (online) · BGE + ONNX Runtime (offline)     |
| Frontend       | React · TypeScript · Vite · Ant Design (planned)            |
| AI Integration | MCP (stdio / SSE dual-mode, planned)                        |


## Design Docs

- **Technical decisions**: [`docs/design.md`](docs/design.md)
- **Retrieval pipeline**: [`docs/instructions/retrieval/`](docs/instructions/retrieval/)
- **Ingestion pipeline**: [`docs/instructions/injestion/`](docs/instructions/injestion/)
- **Rejected designs**: [`docs/rejected_designs.md`](docs/rejected_designs.md)


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
│   │   │   ├── pipeline.py         #   VectorSearcher → RRF → Reranker orchestration
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
├── docs/
│   ├── design.md                   # Technical decision records
│   ├── rejected_designs.md         # Rejected design alternatives
│   ├── backlog.md                  # Task planning and prioritization
│   └── instructions/               # Per-module design specifications
│       ├── core/
│       ├── retrieval/
│       └── injestion/
├── frontend/                       # React + TypeScript (planned)
├── docker-compose.yml
└── CLAUDE.md
```
