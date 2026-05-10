# Recall

Recall is a personal-use local knowledge base retrieval service. It emphasizes **retrieval quality** over generation — combining multi-signal reranking (tag-semantic scoring, Ebbinghaus memory decay), query transformation (rewrite + RAG-Fusion + HyDE), hybrid search (vector + BM25 + contextual BM25), and sophisticated ingestion (auto-tagging, context-aware chunking, content filtering).

Exposed via REST API, CLI, MCP server, and a React frontend.

## Status

- **P0 (Retrieval Core)**: ✅ Complete
- **P1 (Query Transform + API Layer)**: ✅ Complete
- **P2 (Refinement + Testing)**: 🔶 Partial — evaluation framework done; deduplicator/compressor/summarizer not started
- **P3 (MCP + Frontend)**: 🔶 Partial — MCP stdio server done; React frontend with search/library/ingest pages implemented, not yet production-ready

## Architecture

```
Ingestion:
  File → Parser (Text/PDF) → Auto-Tagger (LLM) → Chunker → Contextualizer
  → Content-Filter → Embedder → Dual-write (SQLite + Qdrant)

Query Transform:
  Raw Query → RewriteTransformer / RAGFusionTransformer / HyDeTransformer
           → ComposedTransformer (run multiple strategies concurrently)

Retrieval Pipeline:
  TransformedQuery → Embed → VectorSearcher (Qdrant ANN)        ──┐
                            BM25Searcher (SQLite FTS5)            ├→ RRF Merge → Reranker → Top-K
                            ContextualBM25Searcher (FTS5+context) ──┘

Reranker:
  final_score = α·retrieval_score + β·metadata_score + γ·retention_score
```

## Project Structure

```
Recall/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, exception handlers
│   │   ├── config.py            # Pydantic Settings (.env)
│   │   ├── api/                 # REST routes (documents, search, generate, topology, ingest, stats)
│   │   ├── cli/                 # Typer CLI (ingest, search, generate, eval, docs, reindex, retag...)
│   │   ├── services/            # Service layer shared by API / CLI / MCP
│   │   ├── ingestion/           # Parser → Tagger → Chunker → Contextualizer → Filter → Embedder
│   │   ├── retrieval/           # DAG engine, searchers, reranker, query transforms, RRF merger
│   │   ├── evaluation/          # MRR, nDCG, Recall@k, synthetic query generation
│   │   ├── generation/          # OpenAI-compatible async LLM client
│   │   ├── mcp/                 # MCP stdio server (search / ingest / generate / list_documents)
│   │   └── core/                # ORM models, schemas, database, vectordb, chunk_manager, repository
│   ├── tests/
│   └── pyproject.toml
│
├── frontend/                    # React 19 + TypeScript + Vite + Ant Design
│   └── src/
│       ├── api/                 # Fetch wrappers + TS types
│       ├── pages/               # Search, Library, Ingest
│       └── components/          # ScoreBreakdown, ChatInput, ConfigPanel, etc.
│
├── docker-compose.yml           # Qdrant + backend + frontend
└── docs/                        # Design decisions, backlog, specs
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 · FastAPI · SQLAlchemy 2.0 (async) · aiosqlite |
| Vector DB | Qdrant (Docker) |
| Sparse Search | SQLite FTS5 (BM25) |
| Embedding | GLM Embedding-3 (API) · OpenAI-compatible client |
| Parsers | Text · PyMuPDF · Marker (CLI) · MinerU (API) |
| Frontend | React 19 · TypeScript · Vite · Ant Design |
| MCP | Model Context Protocol · stdio server |

## Quick Start

### Prerequisites

- Python 3.11+, Node.js 18+
- Docker (for Qdrant)

### 1. Start Qdrant

```bash
docker compose up -d qdrant
```

### 2. Backend

```bash
conda create -n rag_env python=3.11
conda activate rag_env
cd backend && pip install -e .

# Configure environment
cp .env.example .env
# Edit .env — set GLM_API_KEY (embedding), LLM_API_KEY (generation/tagging, optional)

# Run
uvicorn app.main:app --reload
```

API is available at `http://localhost:8000`. Swagger docs at `/docs`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dev server at `http://localhost:5173`, proxied to backend on port 8000.

### 4. Docker (full stack)

```bash
docker compose up -d
```

Starts Qdrant, backend (port 8000), and frontend (port 80).

## Usage

### CLI

All CLI commands run from `backend/` with the conda environment activated.

```bash
# Ingest a file
python -m app.cli ingest /path/to/file.pdf --pdf-parser pymupdf --contextualize

# Ingest a directory with concurrency
python -m app.cli ingest /path/to/folder --concurrency 4 --contextualize --strip-markdown

# Search
python -m app.cli search "Modular RAG" --top-k 10 --mode prefer_recent

# RAG generation
python -m app.cli generate "Tell me about Modular RAG"

# Document management
python -m app.cli docs list
python -m app.cli docs delete --all

# Re-tag documents
python -m app.cli retag

# Re-embed after model switch
python -m app.cli reindex

# Evaluation
python -m app.cli eval generate-set --num-chunks 50 --queries-per-chunk 2
python -m app.cli eval run --test-set data/eval_test_set.json --top-k 10
```

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/documents/upload` | Upload and ingest a document |
| `GET` | `/api/documents` | List all documents |
| `GET` | `/api/documents/{id}` | Document details with tags and sync status |
| `DELETE` | `/api/documents/{id}` | Delete document (SQLite + Qdrant) |
| `GET` | `/api/documents/{id}/chunks` | List chunks for a document |
| `PATCH` | `/api/documents/{id}/weight` | Update document weight |
| `POST` | `/api/documents/{id}/reindex` | Re-embed a document |
| `POST` | `/api/documents/{id}/retag` | Regenerate tags |
| `POST` | `/api/documents/{id}/contextualize` | Generate context for chunks |
| `GET` | `/api/documents/{id}/health` | SQLite-Qdrant consistency check |
| `POST` | `/api/search` | Search with configurable topology |
| `POST` | `/generate` | RAG generation (optional SSE streaming) |
| `POST` | `/api/upload` | Upload file (temp storage) |
| `POST` | `/api/ingest` | Start async ingestion task |
| `GET` | `/api/ingest/{task_id}` | Track ingestion progress |
| `GET` | `/api/stats` | System stats |
| `GET` | `/api/tags` | All unique tags |
| `GET/POST/DELETE` | `/api/topology/presets` | Topology preset CRUD |
| `GET` | `/api/topology/node-types` | Available DAG operator types |
| `POST` | `/api/topology/validate` | Validate a pipeline topology |

### MCP Server

```bash
cd backend
python -m app.mcp
```

Exposes `search`, `generate`, `list_documents`, `reindex` tools over stdio for MCP clients (e.g. Claude Desktop).
