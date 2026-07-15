import logging
import time
import uuid

from app.core.llm_client import embed_text
from app.core.llm_providers import get_provider
from app.db.pool import get_conn
from app.services.prompt_versions import get_active_prompt
from app.services.vector_store import hybrid_search

logger = logging.getLogger("supportlm.chat")

# Phase 4 — 3.4: this is now the FALLBACK only, used when a tenant has
# no active_prompt_version_id set. get_active_prompt() returns the
# tenant's configured prompt text when one exists.
_SYSTEM_PROMPT = (
    "You are {agent_name}, a support assistant. Answer the user's question using "
    "ONLY the context provided below. If the context doesn't contain the answer, "
    "say you don't know rather than guessing.\n\nContext:\n{context}"
)


def _render_system_prompt(template: str, agent_name: str, context: str) -> str:
    """template.format() can raise on a tenant-authored prompt_text that
    contains a stray/unescaped brace — an admin's editing mistake
    shouldn't 500 every visitor's chat request until it's fixed.
    Falls back to appending context after the raw template rather than
    silently dropping context or crashing the request."""
    try:
        return template.format(agent_name=agent_name, context=context)
    except (KeyError, IndexError, ValueError):
        logger.warning(
            "Tenant prompt template has a malformed placeholder; falling back to "
            "appending context directly rather than failing the request."
        )
        return f"{template}\n\nContext:\n{context}"


def ask(tenant_id: int, question: str, conversation_id: str | None, agent_name: str = "Assistant") -> dict:
    t0 = time.perf_counter()
    query_vector = embed_text(question)
    t1 = time.perf_counter()

    # Phase 4 — 1.4: hybrid_search() replaces the raw semantic-only
    # MySQLVectorStore.search() call, fusing it with FULLTEXT keyword
    # search per the owner's kickoff decision (weighted blend, not RRF).
    results = hybrid_search(tenant_id, question, query_vector, top_k=5)
    t2 = time.perf_counter()

    context = "\n\n---\n\n".join(
        f"[{r.heading_path or 'Untitled section'}]\n{r.content}" for r in results
    )

    # Phase 4 — 3.4: tenant's active custom prompt (if configured)
    # replaces the hardcoded _SYSTEM_PROMPT default — existing tenants
    # with no configured prompt see zero behavior change.
    template = get_active_prompt(tenant_id) or _SYSTEM_PROMPT
    system_prompt = _render_system_prompt(template, agent_name, context or "(no relevant context found)")
    # Phase 4 — 2.3: per-tenant provider selection replaces the old
    # module-level chat_completion() call, which was hard-wired to
    # DeepSeek regardless of tenant.
    provider = get_provider(tenant_id)
    answer = provider.chat_completion(system_prompt, question)
    t3 = time.perf_counter()

    with get_conn() as conn:
        cur = conn.cursor()

        # If a conversation_id was supplied, only reuse it if it already
        # belongs to this tenant — otherwise silently start a fresh one.
        # Without this, a caller could pass another tenant's
        # conversation_id and have their messages/citations attached to
        # it (or read its history back via the conversation_id they'd
        # then know).
        if conversation_id:
            cur.execute("SELECT tenant_id FROM conversation WHERE id = %s", (conversation_id,))
            existing = cur.fetchone()
            if existing and existing["tenant_id"] != tenant_id:
                conversation_id = None
        conversation_id = conversation_id or str(uuid.uuid4())

        cur.execute(
            """INSERT INTO conversation (id, tenant_id) VALUES (%s, %s)
               ON DUPLICATE KEY UPDATE last_message_at = NOW()""",
            (conversation_id, tenant_id),
        )
        cur.execute(
            "INSERT INTO message (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'user', %s)",
            (tenant_id, conversation_id, question),
        )
        cur.execute(
            "INSERT INTO message (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'assistant', %s)",
            (tenant_id, conversation_id, answer),
        )
        assistant_message_id = cur.lastrowid

        for rank, r in enumerate(results, start=1):
            cur.execute(
                """INSERT INTO citation (tenant_id, message_id, chunk_id, rank, similarity)
                   VALUES (%s, %s, %s, %s, %s)""",
                (tenant_id, assistant_message_id, r.chunk_id, rank, r.similarity),
            )
        cur.close()
    t4 = time.perf_counter()

    logger.info(
        "ask() timing (s) — embed: %.2f, vector_search: %.2f, llm_call: %.2f, db_write: %.2f, total: %.2f",
        t1 - t0, t2 - t1, t3 - t2, t4 - t3, t4 - t0,
    )

    return {
        "conversation_id": conversation_id,
        "answer": answer,
        "sources": [
            {"heading_path": r.heading_path, "similarity": round(r.similarity, 4)}
            for r in results
        ],
    }
