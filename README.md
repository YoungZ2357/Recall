# Recall

Recall is a personal-use local knowledge base retrieval service. It emphasizes **retrieval quality** over generation — combining multi-signal reranking (tag-semantic scoring, Ebbinghaus memory decay), query transformation (rewrite + RAG-Fusion + HyDE), hybrid search (vector + BM25 + contextual BM25), and sophisticated ingestion (auto-tagging, context-aware chunking, content filtering), exposed via CLI, REST API, and MCP server.

## Status

- **P0 (Retrieval Core)**: ✅ Complete
- **P1 (Query Transform + API Layer)**: ✅ Complete (rewrite/RAG-Fusion/HyDE transformers, full REST API, QueryDispatcher stub pending)
- **P2 (Refinement + Testing)**: 🔶 Partial (evaluation framework complete, missing deduplicator/compressor/summarizer, minimal test coverage)
- **P3 (MCP + Frontend)**: 🔶 Partial (stdio MCP server with search/ingest/generate tools, frontend not started)

## Architecture

**Fully Implemented**
```
Ingestion:
  File → Parser (Text/PDF) → Auto-Tagger (LLM) → Chunker → Contextualizer 
  → Content-Filter → Embedder → Dual-write (SQLite + Qdrant)

Query Transform:
  Raw Query → RewriteTransformer (cleaning, disambiguation)
           → RAGFusionTransformer (N variant queries)
           → HyDeTransformer (hypothetical document embedding)
           → ComposedTransformer (mixed strategies)

Retrieval Pipeline:
  TransformedQuery → Embed → VectorSearcher (Qdrant ANN)      ──┐
  Variants          │       BM25Searcher (SQLite FTS5)          ├─→ RRF Merge → Reranker → Return Top-K
                    │       ContextualBM25Searcher (FTS5+context)──┘
  
Reranker (Weighted Multi-Signal):
  final_score = α·retrieval_score + β·metadata_score + γ·retention_score
  where:
    - retrieval_score: vector/BM25 search scores, normalized via RRF
    - metadata_score: max-pooling cosine sim(query_emb, tag_embs) × doc_weight
    - retention_score: Ebbinghaus forgetting curve (access frequency + recency)
```

**Planned / In Progress**
```
Post-Retrieval Refinement (P2):
  ├ Deduplicator (content_hash exact, embedding cosine fuzzy)
  ├ Context Compressor (remove irrelevant sentences)
  └ Summarizer (LLM-based summarization)

MCP + Frontend (P3):
  ├ MCP server SSE (stdio done)
  └ React frontend
```

## Tech Stack

| Layer          | Technology                                              |
|----------------|---------------------------------------------------------|
| Backend        | Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · aiosqlite |
| Vector DB      | Qdrant (Docker)                                         |
| Sparse Search  | SQLite FTS5 (BM25 scoring)                              |
| Embedding      | GLM Embedding-3 (API) · OpenAI-compatible LLM client    |
| Parsers        | Text · PyMuPDF · Marker(CLI) · MinerU (API call)        |
| Evaluation     | MRR · nDCG · Recall@k · Synthetic query synthesis       |
| Frontend       | React · TypeScript · Vite · Ant Design (planned)        |
| MCP            | Model Context Protocol · stdio server                   |

## Key Features

### ✅ Fully Implemented

**Ingestion**
- Multi-format parsing (Text, PDF via PyMuPDF/Marker/MinerU)
- Automatic tag generation (LLM-based document tagging)
- Context-aware chunking (preserves semantic context across chunk boundaries, configurable overlap)
- Content filtering (boilerplate removal, reference stripping, Markdown surgical cleanup)
- Dual-write consistency (SQLite is source of truth, Qdrant is derived)

**Query Transformation**
- Query rewrite (cleaning, keyword expansion, disambiguation via LLM)
- RAG-Fusion (generate N variant queries → parallel search → RRF merge)
- HyDE (Hypothetical Document Embedding — generate fake answer → embed → search)
- Composed transformer (run multiple strategies concurrently)

**Retrieval**
- Hybrid search (vector + BM25 + contextual BM25 with RRF merging)
- Configurable DAG topology (user-defined pipeline graphs, persisted as presets)
- Multi-signal reranking (retrieval score + tag semantics + Ebbinghaus retention)
- Ebbinghaus forgetting curve (tracks access frequency and recency)
- Configurable weighted scoring (α/β/γ parameters)
- Dual-threshold filtering (soft threshold at search, hard threshold at rerank)

**Evaluation**
- Metrics: MRR, nDCG, Recall@k
- Query synthesis (generate synthetic query-document pairs from corpus)
- Configurable samplers (random, diverse, stratified)
- Batch evaluation runner with progress tracking

**API Layer**
- `POST   /api/documents/upload` — Upload and ingest a document
- `GET    /api/documents`         — List all documents
- `GET    /api/documents/{id}`    — Get document details with tags and sync status
- `DELETE /api/documents/{id}`    — Delete a document (SQLite + Qdrant)
- `POST   /api/search`            — End-to-end retrieval with configurable topology
- `POST   /generate`              — Streaming RAG generation
- `GET    /api/topology/node-types`  — List available DAG operator types
- `POST   /api/topology/validate`    — Validate a pipeline topology
- `GET    /api/topology/presets`      — List saved topology presets
- `POST   /api/topology/presets`      — Create a topology preset
- `DELETE /api/topology/presets/{id}` — Delete a topology preset

**CLI Toolkit**
- `ingest <path>` — Ingest files/directories with rich progress UI (configurable parser, chunk strategy, concurrency, contextualization, content filter)
- `search <query>` — Search with detailed scoring breakdown and retention mode
- `generate <query>` — Generate with retrieved context (RAG)
- `eval` — Run retrieval quality assessment, generate synthetic test sets
- `docs` — List/delete documents
- `reindex` — Re-embed entire corpus (model switch)
- `annotate` — Create questions for all chunks in a document
- `contextualize` — Generate context for existing chunks
- `retag` — Re-tag documents with updated LLM-based tags

**Services Layer**
- `IngestionService` — Orchestrates full ingestion pipeline
- `SearchService` — End-to-end retrieval with topology resolution
- `GenerationService` — RAG generation (search → context → LLM)
- `DocumentService` — Document CRUD with chunk statistics
- `ReindexService` — Batch re-embedding on model switch

**MCP Server**
- Stdio server with 3 tools: `search` (ranked chunks with scores), `ingest` (upload files), `generate` (RAG with context)

## Project Structure

```
Recall/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan, exception handlers
│   │   ├── config.py               # Pydantic Settings from env
│   │   │
│   │   ├── api/                    # ✅ HTTP routes
│   │   │   ├── router.py           # Endpoint mounting
│   │   │   ├── dependencies.py     # Dependency injection (services, DB, Qdrant, embedder)
│   │   │   ├── documents.py        # ✅ GET/POST/DELETE /api/documents + upload
│   │   │   ├── search.py           # ✅ POST /api/search (configurable topology)
│   │   │   ├── generate.py         # ✅ POST /generate (streaming LLM)
│   │   │   └── topology.py         # ✅ Topology presets CRUD + validation API
│   │   │
│   │   ├── cli/                    # ✅ CLI interface (Typer)
│   │   │   ├── __main__.py         # `python -m app.cli` dispatcher
│   │   │   ├── ingest.py           # ✅ ingest <path> (rich progress UI, concurrency, content filter)
│   │   │   ├── search.py           # ✅ search <query> (scoring details, retention mode)
│   │   │   ├── generate.py         # ✅ generate <query> (RAG with context)
│   │   │   ├── reindex.py          # ✅ reindex (re-embed on model switch)
│   │   │   ├── docs.py             # ✅ docs (list/delete documents)
│   │   │   ├── annotate.py         # ✅ annotate (chunk-level annotations for eval)
│   │   │   ├── contextualize.py    # ✅ contextualize (context generation)
│   │   │   ├── retag.py            # ✅ retag (re-tag documents with LLM)
│   │   │   ├── eval.py             # ✅ eval (retrieval quality assessment + synth set generation)
│   │   │   └── _init_deps.py       # Shared dependency wiring
│   │   │
│   │   ├── services/               # ✅ Service layer (API/CLI/MCP backends)
│   │   │   ├── document_service.py # ✅ Document CRUD + chunk stats
│   │   │   ├── search_service.py   # ✅ End-to-end retrieval + topology
│   │   │   ├── ingestion_service.py# ✅ Ingestion orchestration
│   │   │   ├── generation_service.py# ✅ RAG generation
│   │   │   └── reindex_service.py  # ✅ Batch re-embedding
│   │   │
│   │   ├── ingestion/              # ✅ Document ingestion pipeline
│   │   │   ├── pipeline.py         # ✅ Orchestration
│   │   │   ├── parser.py           # ✅ Format dispatcher
│   │   │   ├── parsers/
│   │   │   │   ├── text.py         # ✅ Plain text (.txt, .md)
│   │   │   │   ├── pdf.py          # ✅ Marker CLI parser
│   │   │   │   ├── pdf_pymupdf.py  # ✅ PyMuPDF parser
│   │   │   │   └── pdf_mineru.py   # ✅ MinerU API parser
│   │   │   ├── chunker.py          # ✅ RecursiveSplit, FixedCount
│   │   │   ├── embedder.py         # ✅ APIEmbedder (GLM Embedding-3)
│   │   │   ├── tagger.py           # ✅ Auto-tagger (LLM-based)
│   │   │   ├── contextualizer.py   # ✅ Contextual retrieval (KV-cache optimized)
│   │   │   └── content_filter.py   # ✅ Boilerplate removal, noise filtering, Markdown cleanup
│   │   │
│   │   ├── retrieval/              # ✅ Retrieval core (complete)
│   │   │   ├── pipeline.py         # ✅ Full orchestration + hydration + access recording
│   │   │   ├── searcher.py         # ✅ VectorSearcher (Qdrant ANN)
│   │   │   │                       # ✅ BM25Searcher (SQLite FTS5)
│   │   │   │                       # ✅ ContextualBM25Searcher (FTS5 on context)
│   │   │   ├── reranker.py         # ✅ Weighted multi-signal scoring
│   │   │   │                       # ✅ Tag-semantic scoring (metadata)
│   │   │   │                       # ✅ Ebbinghaus retention (forgetting curve)
│   │   │   ├── operators.py        # ✅ Base interfaces: BaseRetriever, BaseReranker, etc.
│   │   │   ├── engine.py           # ✅ DAG execution engine (topo sort → run → collect)
│   │   │   ├── graph.py            # ✅ DAG topology builder + validation
│   │   │   ├── workflows.py        # ✅ Predefined topology factories
│   │   │   ├── merger.py           # ✅ RRFMerger operator
│   │   │   ├── scoring.py          # ✅ Stateless scoring: normalize_scores, reciprocal_rank_fusion
│   │   │   ├── configs.py          # ✅ Searcher/reranker/transformer config classes
│   │   │   ├── registry.py         # ✅ Operator type registry (mapping JSON names to classes)
│   │   │   ├── topology.py         # ✅ JSON ↔ GraphSpec bridge, DB persistence helpers
│   │   │   └── query_transform.py  # ✅ Rewrite + RAG-Fusion + HyDE + Composed transformers
│   │   │                           # 🔶 QueryDispatcher stub (P1-8 pending)
│   │   │
│   │   ├── evaluation/             # ✅ Evaluation framework
│   │   │   ├── metrics.py          # ✅ MRR, nDCG, Recall@k
│   │   │   ├── runner.py           # ✅ Evaluation orchestrator
│   │   │   ├── sampler.py          # ✅ Query-doc sampling strategies
│   │   │   └── synthesizer.py      # ✅ Synthetic query generation
│   │   │
│   │   ├── generation/             # ✅ LLM generation
│   │   │   └── generator.py        # ✅ OpenAI-compatible async client
│   │   │
│   │   ├── refiner/                # ❌ Empty (dedup/compress/summarize planned)
│   │   ├── mcp/                    # ✅ MCP stdio server
│   │   │   ├── server.py           # ✅ Stdio server (search/ingest/generate tools)
│   │   │   └── __main__.py         # ✅ Entry point
│   │   │
│   │   └── core/                   # ✅ Shared infrastructure
│   │       ├── models.py           # ✅ ORM (Document, Chunk, ChunkAccess, TopologyConfig)
│   │       ├── schemas.py          # ✅ Pydantic models
│   │       ├── database.py         # ✅ Async SQLAlchemy + aiosqlite
│   │       ├── vectordb.py         # ✅ Qdrant wrapper
│   │       ├── repository.py       # ✅ Data access layer
│   │       ├── chunk_manager.py    # ✅ SQLite ↔ Qdrant consistency
│   │       ├── pipeline_deps.py    # ✅ PipelineDeps dataclass
│   │       └── exceptions.py       # ✅ Custom exception hierarchy
│   │
│   ├── tests/                      # Minimal test coverage (test_sqalchemy_conn/)
│   └── pyproject.toml
│
├── frontend/                       # ❌ Not started (React + TS planned)
│
├── docs/
│   ├── design.md                   # Technical decisions
│   ├── backlog.md                  # Prioritized task list
│   ├── rejected_designs.md         # Design alternatives considered
│   └── instructions/               # Per-module specs
│
├── docker-compose.yml
└── AGENTS.md                       # Project guidelines for AI agents
```

## Quick Start

### Prerequisites
- Python 3.11+
- Qdrant running in Docker
- Environment variables configured

### Setup

```bash
# Start Qdrant
docker compose up -d qdrant

# Create conda environment and install dependencies
conda create -n rag_env python=3.11
conda activate rag_env
cd backend && pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your API keys (GLM_API_KEY, etc.)
```

### Start the API Server

```bash
conda activate rag_env
cd backend && uvicorn app.main:app --reload
```

### CLI Examples

```bash
# List all documents
python -m app.cli docs list

# Ingest a single file (with contextualization and content filter)
python -m app.cli ingest --pdf-parser mineru --contextualize --chunk-size 1024 /path/to/file.pdf

# Ingest a directory (async, document-wise, with concurrency)
python -m app.cli ingest --pdf-parser pymupdf --contextualize --concurrency 4 /path/to/folder

# Ingest with content filtering (strip Markdown reference sections)
python -m app.cli ingest --contextualize --strip-markdown /path/to/folder

# Retag documents missing tags
python -m app.cli retag

# Search with retention mode
python -m app.cli search "Modular RAG" --top-k 10 --mode prefer_recent

# Generate a RAG answer
python -m app.cli generate "Tell me about Modular RAG"

# Generate synthetic evaluation set
python -m app.cli eval generate-set --num-chunks 50 --queries-per-chunk 2

# Run evaluation
python -m app.cli eval run --test-set data/eval_test_set.json --top-k 10

# Delete all documents
python -m app.cli docs delete --all
```

### MCP Server

```bash
# Start the MCP stdio server
python -m app.mcp

# Available tools: search, ingest, generate
```
