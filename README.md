# SupportLM — Phase 1: KnowledgeLM

A company uploads Markdown documents. AI answers questions accurately. Nothing else.

## Stack
- **Backend:** Python 3.11+, FastAPI
- **DB:** MySQL 8+ (single-tenant per install)
- **Vector search:** embeddings stored in MySQL, brute-force cosine similarity via `VectorStore`
  interface (swappable later — see `app/services/vector_store.py`)
- **Frontend:** server-rendered templates + minimal vanilla JS (no framework)

## Project layout
```
app/
  api/          FastAPI routers (chat, documents, admin, installer)
  core/         config, security, embeddings client
  db/           connection pool, schema
  models/       typed dataclasses / row mappers (no ORM — raw SQL, clean & explicit)
  services/     business logic: ingestion, chunking, vector store, chat
migrations/     versioned .sql files (001_init.sql, ...)
static/js/      chat widget (vanilla JS, ~1 file)
templates/      Jinja2 templates for admin dashboard + installer
scripts/        one-off ops scripts (e.g. reindex)
tests/
```

## Setup
```bash
cp .env.example .env          # fill in DB creds + embedding API key
pip install -r requirements.txt
python scripts/init_db.py     # runs migrations/001_init.sql
python scripts/create_admin.py owner@company.com yourpassword   # first admin login
uvicorn app.main:app --reload
```

Then visit `/` for the chat UI and `/admin` to log in and manage categories/documents.

## Design decisions (Phase 1)
- **Single-tenant per install.** The installer provisions one company per deployment.
  No `company_id` scoping needed in Phase 1 — simplifies schema and queries. This is
  revisited if/when Phase 3+ moves toward multi-tenant hosting.
- **MySQL for everything, including embeddings.** No external vector DB. Embeddings
  stored as JSON float arrays in `embeddings.vector`; similarity computed in Python
  over candidate chunks. Fine at the scale of Phase 1 customers (hundreds–low
  thousands of chunks). The `VectorStore` interface isolates this decision so it can
  be swapped for pgvector/Qdrant/etc. later without touching call sites.
- **No ORM.** Raw SQL via a thin connection pool wrapper, typed row-mapping. Keeps the
  schema and queries explicit and auditable — appropriate for a small, fixed set of
  12 tables.
