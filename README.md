# Recall
Recall is a personal-use local knowledge base retrieval service. It focuses on high-quality document retrieval, 
multi-dimensional reordering, and post-retrieval contextual refinement, rather than end-to-end generation.


## Architecture
```
Query → Query Transform → Vector Recall → Reranking → Refinement → Return Context
             │                 │              │             │
        query_transform     searcher       reranker      refiner/
        ├ RAG-Fusion        Qdrant ANN     ├ Cross-Encoder     ├ deduplicator
        ├ HyDE                             ├ Metadata weights  ├ context_compressor
        └ Query rewriting                  ├ Graph signals     └ summarizer
                                           └ Memory decay (Ebbinghaus)

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
│   │   ├── api/                    # HTTP routes
│   │   │   ├── documents.py        #   Document CRUD
│   │   │   ├── search.py           #   Search endpoint
│   │   │   └── generate.py         #   Basic generation (optional)
│   │   ├── ingestion/              # Document ingestion
│   │   │   ├── parser.py           #   File parsing
│   │   │   ├── chunker.py          #   Chunking strategies
│   │   │   └── embedder.py         #   Dual-mode embedding
│   │   ├── retrieval/              # Retrieval core
│   │   │   ├── query_transform.py  #   Query transformation
│   │   │   ├── searcher.py         #   Vector recall (ANN)
│   │   │   └── reranker.py         #   Multi-signal reranking
│   │   ├── refiner/                # Post-retrieval refinement
│   │   │   ├── pipeline.py         #   Pipeline orchestration
│   │   │   ├── context_compressor.py
│   │   │   ├── summarizer.py
│   │   │   └── deduplicator.py
│   │   ├── generation/             # Minimal generation
│   │   │   └── generator.py
│   │   ├── mcp/                    # MCP service
│   │   │   ├── server.py
│   │   │   └── tools.py
│   │   └── core/                   # Shared infrastructure
│   │       ├── database.py         #   SQLAlchemy async engine
│   │       ├── models.py           #   ORM models
│   │       ├── schemas.py          #   Pydantic models
│   │       ├── vectordb.py         #   Qdrant client
│   │       ├── chunk_manager.py    #   Lifecycle management
│   │       ├── dependencies.py     #   FastAPI DI
│   │       └── exceptions.py
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
├── docker-compose.yml
└── CLAUDE.md
```