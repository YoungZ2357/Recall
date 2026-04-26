# AGENTS.md

## Project Overview

Recall is a knowledge base retrieval system with intelligent reranking and minimal generation.
- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2.0 (async + aiosqlite), Qdrant, Pydantic
- **Frontend**: Vite + React + TypeScript + Ant Design (P3, not yet initialized)
- **Package managers**: pip (backend/pyproject.toml), npm (frontend/package.json)
- **Python env**: `conda activate rag_env`

---

## Common Commands

```bash
# Start Qdrant (required)
docker compose up qdrant -d

# Backend server
cd backend
uvicorn app.main:app --reload

# Frontend dev (when initialized)
cd frontend
npm install && npm run dev
```

---

## Lint & Format

```bash
cd backend

# Ruff — lint + auto-fix
ruff check .
ruff check . --fix

# Subset of checks used (pyproject.toml [tool.ruff.lint]):
#   E/W (pycodestyle), F (pyflakes), I (isort), UP (pyupgrade), B (bugbear), ASYNC
```

No type checker is configured yet (mypy/pyright not in dev deps). Use `ruff` for linting only.

---

## Test

```bash
cd backend

# All tests
pytest

# Single test file
pytest tests/test_sqalchemy_conn/test_database.py

# Single test function
pytest tests/test_sqalchemy_conn/test_database.py::TestDatabase::test_create_async_engine_from_settings

# Single test with verbose output
pytest tests/test_sqalchemy_conn/test_database.py -v -k "test_create_tables"
```

Pytest config (`pyproject.toml`):
- `asyncio_mode = "auto"` — async test functions are auto-detected with `@pytest.mark.asyncio`
- `testpaths = ["tests"]`

---

## Code Style

### Python

**Imports** — enforced by `ruff` with `isort`:
- Standard library first, then third-party, then first-party (`app.*`)
- Do NOT re-export from `__init__.py`; use full import paths

**SQLAlchemy 2.0 style**:
- `Mapped[]` type annotations, `mapped_column()`, `relationship()` with inferred target classes
- All DB access through ORM — no raw SQL

**Type annotations**:
- Every function signature must annotate parameter types and return type
- Use `Pydantic` models for request/response schemas (separate from ORM models in `models.py`)

**Datetime**:
- Always timezone-aware: `datetime.now(timezone.utc)`, never `datetime.utcnow()`

**Async**:
- Full-stack async/await: aiosqlite for DB, httpx.AsyncClient for HTTP, all FastAPI routes `async def`
- Parse operations run in thread pool via `asyncio.to_thread()`

### Naming Conventions

| Category | Style | Example |
|----------|-------|---------|
| Python files / variables / functions | snake_case | `chunk_manager.py`, `get_document_by_id()` |
| Python classes | PascalCase | `ChunkManager`, `APIEmbedder` |
| Constants | UPPER_SNAKE_CASE | `MAX_CHUNK_SIZE`, `DEFAULT_TOP_K` |
| TS files | kebab-case | `document-list.tsx` |
| TS variables / functions | camelCase | `fetchDocuments()` |
| TS components / types | PascalCase | `DocumentList`, `SearchResult` |

### Error Handling

- Custom exception classes in `app/core/exceptions.py`, converted to HTTP responses via FastAPI exception handlers
- Use `logging` (not `print`) for all logs
- Failures in Qdrant/SQLite coordinated by `chunk_manager.py` for rollback or `sync_status=FAILED`

---

## Project Structure

```
backend/
  app/
    main.py                  # FastAPI app, CORS, lifespan
    config.py                # Pydantic Settings (env vars)
    core/                    # models, schemas, database, chunk_manager, vectordb, repository, exceptions
    ingestion/               # pipeline, parser, chunker, embedder, tagger, contextualizer, content_filter
    retrieval/               # pipeline, workflows, graph, engine, operators, searcher, reranker, merger, configs
    api/                     # routes: documents, search, generate
    cli/                     # Typer CLI: ingest, search, reindex, eval, generate, docs
    mcp/                     # MCP server (stdio)
    generation/              # LLM generator
    evaluation/              # eval runner, metrics, synthesizer, sampler
    refiner/                 # dedup, compress, summarize (P2)
  tests/
.docker-compose.yml
docs/backlog.md              # Task planning
docs/design.md               # Technical decision records
```

---

## Hard Rules (highest priority, non-negotiable)

1. **Data consistency**: All document CRUD must go through `chunk_manager.py` — it coordinates SQLite + Qdrant. Never bypass it.
2. **SQLite is Source of Truth**: Qdrant is a rebuildable derived store. In a worst-case scenario, Qdrant can be fully reconstructed from SQLite.
3. **Shared primary key**: Every chunk uses a UUID as `chunk_id`, shared between SQLite and Qdrant.
4. **Embedding model tracking**: When switching models, record `embedding_model` and trigger re-embedding. Vectors of different dimensions must not mix in the same collection.
5. **Secrets**: API keys only via environment variables. Never hardcode.
6. **Database access**: Use SQLAlchemy ORM exclusively. No raw SQL.
7. **Existing tests**: Do not modify existing tests unless explicitly asked.

## Communication Style

- Reply language: 中文
- Code comments: English
- Be concise; expand only when necessary
- Ask questions when uncertain — don't guess
- Critically analyze provided code and point out issues directly

## Workflow Constraints

- Plan first, code second. Wait for explicit confirmation before coding.
- Write only what is explicitly requested. Do not proactively add unrequested features.
- After completing changes, run `ruff check .` and `pytest` to verify correctness.
