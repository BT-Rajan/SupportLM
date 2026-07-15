# Phase 4 WBS — Retrieval & Answer Quality

> Scope source: `docs/MASTER_PROMPT.md` Section 3, "Phase 4". Nothing
> here expands that scope; this file breaks it into buildable, ordered
> rounds the way `docs/Phase I/II/III WBS.md` did for their phases.

Phase 4 scope, verbatim from the master prompt: hybrid search
(keyword + semantic combined, on the existing MySQL store — no vector
DB migration). Multi-LLM provider support (pluggable providers, not
hard-wired to one DeepSeek key). Prompt versioning (edit/roll back
system prompts without a redeploy).

## Note on Phase 3 status

Owner has confirmed Phase 3 (Knowledge Base Management) is complete,
built outside this repo/session. `docs/STATUS.md`'s round log up to
Round 20 only shows Phase 3 planning — that gap is called out
explicitly there rather than silently overwritten, since this session
cannot independently verify the 1.0-6.0 build. Phase 4 proceeds on the
owner's word per `MASTER_PROMPT.md` §2.1 (this file / STATUS.md are
authoritative for *scope*, not a substitute for the owner's own
sign-off on what's actually been built).

## Owner decisions confirmed at kickoff

- **1.0 hybrid search fusion**: MySQL `FULLTEXT` index on
  `document_chunk.content`, combined with the existing cosine-similarity
  vector search via a **weighted score blend** — not reciprocal rank
  fusion (RRF), not a keyword-only fallback. Both signals normalized to
  [0,1] and blended with a tunable weight before ranking, so the same
  result set can be produced with either signal silenced (weight 0) for
  testing/debugging.
- **2.0 multi-LLM providers**: DeepSeek, OpenAI, and Anthropic, all
  pluggable behind one interface. **Selectable per-tenant** — a
  `tenant`-level setting picks the active provider + model, not a
  single global env var. Embeddings stay local via
  `sentence_transformers` regardless of chat provider (Phase 1's
  existing rationale — not every provider even has an embeddings
  endpoint, and switching embedding models mid-flight would invalidate
  every stored vector).
- **3.0 prompt versioning**: **per-tenant**, editable via the admin UI,
  with rollback to any prior version. Not global — branding (4.1,
  Phase 1) is already per-tenant and the system prompt is the other
  half of a tenant's "voice," so the two should be configurable at the
  same level.

## A design note worth flagging before 1.1

`app/core/llm_client.py` currently hard-codes both the chat completion
call (DeepSeek-shaped request/response) and the embedding call in one
file with no provider abstraction — Phase 1 documented this as
temporary ("Phase 4" is named directly in `MASTER_PROMPT.md` §2.6 as
where this gets fixed). 2.0 replaces it with a `ChatProvider` protocol
(mirroring the existing `VectorStore` protocol pattern from
`vector_store.py`) with one implementation per provider
(`DeepSeekProvider`, `OpenAIProvider`, `AnthropicProvider`), selected at
call time by the resolved tenant's stored provider setting — not at
import time — since providers are now a per-request, per-tenant choice
rather than one process-wide constant.

## Dependency order

1.0 and 2.0 are independent of each other (hybrid search touches
retrieval; provider swapping touches generation) and could be built in
either order. 3.0 (prompt versioning) depends on nothing from 1.0/2.0
structurally, but is sequenced last because `app/services/chat.py`'s
`ask()` function is the one place all three land — building hybrid
search and multi-provider first, then prompt versioning, means the
final edit to `ask()` only has to happen once instead of three separate
times touching the same function.

## 1.0 Hybrid Search

- **1.1 Schema**: `migrations/015_hybrid_search.sql` adds a MySQL
  `FULLTEXT` index on `document_chunk.content` (`ALTER TABLE
  document_chunk ADD FULLTEXT INDEX ft_content (content)`, requires
  InnoDB's native FULLTEXT support, available since MySQL 5.6/MariaDB
  10.0 — no engine change needed, existing table already InnoDB).
- **1.2 Keyword search** (`app/services/vector_store.py`): new
  `keyword_search(tenant_id, query, top_k)` using `MATCH(content)
  AGAINST(%s IN NATURAL LANGUAGE MODE)`, tenant-scoped and
  `status='ready'`-scoped identically to the existing
  `MySQLVectorStore.search()`, returning the same `SearchResult` shape
  plus a raw MySQL relevance score.
- **1.3 Score fusion**: new `hybrid_search(tenant_id, query,
  query_vector, top_k, keyword_weight=0.3)` — runs both searches,
  min-max normalizes each result set's scores independently to [0,1]
  (since cosine similarity and MySQL's relevance score are on
  incomparable scales), unions on `chunk_id`, computes
  `final_score = (1 - keyword_weight) * semantic_norm + keyword_weight
  * keyword_norm` (a chunk missing from one side scores 0 on that
  side, not excluded), sorts, returns `top_k`. `keyword_weight` is a
  named parameter specifically so it can be set to 0 or 1 in tests to
  isolate each signal.
- **1.4 Wire into `ask()`**: `app/services/chat.py` calls
  `hybrid_search()` instead of `_store.search()` directly.

## 2.0 Multi-LLM Provider Support

- **2.1 Schema**: `migrations/016_llm_provider_config.sql` adds
  `tenant_llm_config` (1:1 with `tenant`: `provider ENUM('deepseek',
  'openai','anthropic')`, `model`, `api_key_encrypted` NULL — falls
  back to the existing global `settings.llm_api_key` env var if NULL,
  so tenants who don't set their own key still work against the
  install's shared key/provider, matching Phase 1's branding
  fallback-not-inferred pattern: explicit per-tenant override, sane
  default otherwise).
- **2.2 Provider abstraction** (`app/core/llm_providers.py`): a
  `ChatProvider` protocol (`chat_completion(system_prompt,
  user_message) -> str`) with `DeepSeekProvider`, `OpenAIProvider`,
  `AnthropicProvider` — each wraps that provider's actual chat-completions
  shape (DeepSeek/OpenAI are both OpenAI-compatible REST; Anthropic's
  `/v1/messages` has a distinct request/response shape, handled in its
  own class rather than forced into the OpenAI-compatible one).
  `get_provider(tenant_id)` resolves the tenant's `tenant_llm_config`
  row (or the global default) and returns the right instance.
- **2.3 Wire into `ask()`**: `app/services/chat.py` calls
  `get_provider(tenant_id).chat_completion(...)` instead of the
  module-level `chat_completion` import from `llm_client.py`.
  `llm_client.py` keeps only `embed_text()` — embeddings aren't
  provider-pluggable per the kickoff decision above.
- **2.4 Admin endpoint + UI**: `POST /api/tenant/llm-config`
  (`admin`+, sets provider/model/api_key for the calling tenant) and a
  settings panel in `admin.html` to configure it, following the same
  "script exists first, UI catches up" pattern only if the UI slips —
  otherwise built in the same round as 2.1-2.3.

## 3.0 Prompt Versioning

- **3.1 Schema**: `migrations/017_prompt_versions.sql` adds
  `tenant_prompt_version` (id, tenant_id, version_number, prompt_text,
  created_at, created_by_admin_id NULL `ON DELETE SET NULL` —
  mirroring `api_key.created_by_admin_id`'s exact rationale: deleting
  the editing admin shouldn't invalidate a live prompt) and
  `tenant.active_prompt_version_id` NULL (NULL = use the hardcoded
  `_SYSTEM_PROMPT` default in `chat.py`, matching the branding/LLM-config
  fallback pattern rather than requiring every tenant to have a row).
- **3.2 Version management service** (`app/services/prompt_versions.py`):
  `create_version(tenant_id, prompt_text, admin_id)` — inserts a new
  row with the next `version_number`, does **not** auto-activate it
  (activation is explicit, so an admin can draft/preview before making
  it live — same "no more instant-live" spirit Phase 3 established for
  documents). `activate_version(tenant_id, version_id)` sets
  `tenant.active_prompt_version_id`, rejecting a `version_id` that
  doesn't belong to the tenant (same cross-tenant guard pattern as
  every other Phase 1-3 write path). `get_active_prompt(tenant_id)`
  returns the active version's text or the hardcoded default.
- **3.3 Admin endpoints + UI**: `POST /api/tenant/prompt-versions`
  (create, `editor`+), `POST
  /api/tenant/prompt-versions/{id}/activate` (`admin`+ — rollback is
  just activating an older version, no separate "rollback" endpoint
  needed), `GET /api/tenant/prompt-versions` (list, `viewer`+). Admin
  UI: a prompt editor + version history list with an "activate" action
  per past version, in `admin.html`.
- **3.4 Wire into `ask()`**: `app/services/chat.py`'s `_SYSTEM_PROMPT`
  module constant becomes the fallback only; `ask()` calls
  `get_active_prompt(tenant_id)` and formats whichever text comes back
  with `{agent_name}`/`{context}` the same way it does today —
  existing tenants with no configured prompt see zero behavior change.

## 4.0 Testing & Validation

Same shape as Phases 2/3: round-by-round tests land alongside each
round above, DB-gated tests skip cleanly with no DB reachable, plus a
final full-suite pass on a freshly rebuilt database (not reused state)
once 1.0-3.0 are done — same discipline Round 19 used for Phase 2.

## 5.0 Documentation & Handoff

`docs/STATUS.md` updated per round. Any new admin UI surface (LLM
config panel, prompt editor/version list) documented in
`docs/DESIGN_SYSTEM.md` as it's built, not deferred to a closing round.
