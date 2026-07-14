import logging
import time
import uuid

from app.core.llm_client import chat_completion, embed_text
from app.db.pool import get_conn
from app.services.vector_store import MySQLVectorStore

logger = logging.getLogger("supportlm.chat")

_SYSTEM_PROMPT = (
    "You are {agent_name}, a support assistant. Answer the user's question using "
    "ONLY the context provided below. If the context doesn't contain the answer, "
    "say you don't know rather than guessing.\n\nContext:\n{context}"
)

_store = MySQLVectorStore()


def ask(tenant_id: int, question: str, conversation_id: str | None, agent_name: str = "Assistant") -> dict:
    t0 = time.perf_counter()
    query_vector = embed_text(question)
    t1 = time.perf_counter()

    results = _store.search(tenant_id, query_vector, top_k=5)
    t2 = time.perf_counter()

    context = "\n\n---\n\n".join(
        f"[{r.heading_path or 'Untitled section'}]\n{r.content}" for r in results
    )

    system_prompt = _SYSTEM_PROMPT.format(agent_name=agent_name, context=context or "(no relevant context found)")
    answer = chat_completion(system_prompt, question)
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
