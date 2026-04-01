# Recall

Recall is a personal-use local knowledge base retrieval service. It emphasizes **retrieval quality** over generation — combining multi-signal reranking (tag-semantic scoring, Ebbinghaus memory decay), hybrid search (vector + BM25), and sophisticated ingestion (auto-tagging, context-aware chunking), exposed via CLI and REST API.

## Status

- **P0 (Retrieval Core)**: ✅ Complete
- **P1 (Query Transform + API Layer)**: 🔶 Partial (FastAPI initialized, /generate endpoint, missing documents/search API routes and query transformation)
- **P2 (Refinement + Testing)**: 🔶 Partial (evaluation framework complete, missing deduplicator/compressor/summarizer)
- **P3 (MCP + Frontend)**: ❌ Not started

## Architecture

**Fully Implemented**
```
Ingestion:
  File → Parser (Text/PDF) → Auto-Tagger (LLM) → Chunker → Contextualizer 
  → Content-Filter → Embedder → Dual-write (SQLite + Qdrant)

Retrieval Pipeline:
  Query → Embed → VectorSearcher (Qdrant ANN)  ──┐
                  BM25Searcher (SQLite FTS5)     ├─→ RRF Merge → Reranker → Return Top-K
  
Reranker (Weighted Multi-Signal):
  final_score = α·retrieval_score + β·metadata_score + γ·retention_score
  where:
    - retrieval_score: vector/BM25 search scores, normalized via RRF
    - metadata_score: max-pooling cosine sim(query_emb, tag_embs) × doc_weight
    - retention_score: Ebbinghaus forgetting curve (access frequency + recency)
```

**Planned / In Progress**
```
Query Transform (P1-1,2,3):
  ├ RAG-Fusion (generate N query variants → merge results)
  ├ HyDE (generate hypothesis → embed → search)
  └ Basic query rewriting

Post-Retrieval Refinement (P2):
  ├ Deduplicator (content_hash exact, embedding cosine fuzzy)
  ├ Context Compressor (remove irrelevant sentences)
  └ Summarizer (LLM-based summarization)

API Exposure (P1-5,6):
  ├ POST /documents (ingest)
  ├ GET /documents (list, details)
  └ POST /search (end-to-end retrieval)

MCP + Frontend (P3):
  ├ MCP server (stdio/SSE)
  └ React frontend
```

## Tech Stack

| Layer          | Technology                                              |
|----------------|---------------------------------------------------------|
| Backend        | Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · aiosqlite |
| Vector DB      | Qdrant (Docker)                                         |
| Sparse Search  | SQLite FTS5 (BM25 scoring)                              |
| Embedding      | GLM Embedding-3 (API) · OpenAI-compatible LLM client    |
| Parsers        | Text · PyMuPDF · Marker(CLI) · MinerU (API call)                  |
| Evaluation     | MRR · nDCG · Recall@k · Synthetic query synthesis       |
| Frontend       | React · TypeScript · Vite · Ant Design (planned)        |
| MCP            | (planned)                                |


## Key Features

### ✅ Fully Implemented

**Ingestion**
- Multi-format parsing (Text, PDF via PyMuPDF/Marker/MinerU)
- Automatic tag generation (LLM-based document tagging)
- Context-aware chunking (preserves semantic context across chunk boundaries)
- Boilerplate filtering (removes noise, references, formatting artifacts)
- Dual-write consistency (SQLite is source of truth, Qdrant is derived)

**Retrieval**
- Hybrid search (vector + BM25 with RRF merging)
- Multi-signal reranking (retrieval score + tag semantics + Ebbinghaus retention)
- Ebbinghaus forgetting curve (tracks access frequency and recency)
- Configurable weighted scoring (α/β/γ parameters)
- Dual-threshold filtering (soft threshold at search, hard threshold at rerank)

**Evaluation**
- Metrics: MRR, nDCG, Recall@k
- Query synthesis (generate synthetic query-document pairs from corpus)
- Configurable samplers (random, diverse, stratified)
- Batch evaluation runner with progress tracking

**CLI Toolkit**
- `ingest <path>` — Ingest files/directories with rich progress UI
- `search <query>` — Search with detailed scoring breakdown
- `generate <query>` — Generate with retrieved context (retrieval-augmented generation)
- `eval` — Run retrieval quality assessment
- `docs` — List/delete documents
- `reindex` — Re-embed entire corpus (model switch)
- `annotate` — Create questions for all chunks in a document
- `contextualize` — Generate context for existing chunks, which may help with embedding




## Project Structure

```
Recall/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan, exception handlers
│   │   ├── config.py               # Pydantic Settings from env
│   │   │
│   │   ├── api/                    # ✅ HTTP routes (WIP: only /generate)
│   │   │   ├── router.py           # Endpoint mounting
│   │   │   ├── generate.py         # ✅ POST /generate (streaming LLM)
│   │   │   └── dependencies.py     # ✅ Dependency injection
│   │   │
│   │   ├── cli/                    # ✅ CLI interface (Typer)
│   │   │   ├── __main__.py         # `python -m app.cli` dispatcher
│   │   │   ├── ingest.py           # ✅ ingest <path> (rich progress UI)
│   │   │   ├── search.py           # ✅ search <query> (scoring details)
│   │   │   ├── generate.py         # ✅ generate <query> (with context)
│   │   │   ├── reindex.py          # ✅ reindex (re-embed on model switch)
│   │   │   ├── docs.py             # ✅ docs (list/delete documents)
│   │   │   ├── annotate.py         # ✅ annotate (chunk-level annotations for eval)
│   │   │   ├── contextualize.py    # ✅ contextualize (context generation)
│   │   │   ├── eval.py             # ✅ eval (retrieval quality assessment)
│   │   │   └── _init_deps.py       # Shared dependency wiring
│   │   │
│   │   ├── ingestion/              # ✅ Document ingestion pipeline
│   │   │   ├── pipeline.py         # ✅ Orchestration
│   │   │   ├── parser.py           # ✅ Format dispatcher
│   │   │   ├── parsers/
│   │   │   │   ├── text.py         # ✅ Plain text
│   │   │   │   └── pdf.py          # ✅ PyMuPDF, Marker, MinerU
│   │   │   ├── chunker.py          # ✅ RecursiveSplit, FixedCount
│   │   │   ├── embedder.py         # ✅ APIEmbedder (GLM Embedding-3)
│   │   │   ├── tagger.py           # ✅ Auto-tagger (LLM-based)
│   │   │   ├── contextualizer.py   # ✅ Contextual retrieval (KV-cache optimized)
│   │   │   └── content_filter.py   # ✅ Boilerplate removal, noise filtering
│   │   │
│   │   ├── retrieval/              # ✅ Retrieval core (complete)
│   │   │   ├── pipeline.py         # ✅ Full orchestration + hydration
│   │   │   ├── searcher.py         # ✅ VectorSearcher (Qdrant ANN)
│   │   │   │                       # ✅ BM25Searcher (SQLite FTS5)
│   │   │   │                       # ✅ RRF merge algorithm
│   │   │   ├── reranker.py         # ✅ Weighted multi-signal scoring
│   │   │   │                       # ✅ Tag-semantic scoring (metadata)
│   │   │   │                       # ✅ Ebbinghaus retention (forgetting curve)
│   │   │   ├── operators.py        # Base interfaces (extensible)
│   │   │   └── query_transform.py  # ❌ Empty (RAG-Fusion, HyDE planned)
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
│   │   ├── mcp/                    # ❌ Empty (MCP server planned)
│   │   │
│   │   └── core/                   # ✅ Shared infrastructure
│   │       ├── models.py           # ✅ ORM (Document, Chunk, ChunkAccess)
│   │       ├── schemas.py          # ✅ Pydantic models
│   │       ├── database.py         # ✅ Async SQLAlchemy + aiosqlite
│   │       ├── vectordb.py         # ✅ Qdrant wrapper
│   │       ├── repository.py       # ✅ Data access layer
│   │       ├── chunk_manager.py    # ✅ SQLite ↔ Qdrant consistency
│   │       └── exceptions.py       # Custom exception hierarchy
│   │
│   ├── tests/                      # Minimal test coverage
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
└── CLAUDE.md                       # Project guidelines
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
conda create -n recall python=3.11
conda activate recall
cd backend && pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your API keys (GLM_API_KEY, etc.)
```

### Basic Workflow

```bash
# 1. Ingest documents
python -m app.cli ingest path/to/documents/

# 2. Search knowledge base
python -m app.cli search "your query"

# 3. Generate answer with retrieved context
python -m app.cli generate "your question"

# 4. Evaluate retrieval quality
python -m app.cli eval --queries evaluation_queries.jsonl

# List documents
python -m app.cli docs list

# Delete a document
python -m app.cli docs delete <document_id>

# Re-embed corpus (after model switch)
python -m app.cli reindex --model new_model_name
```




