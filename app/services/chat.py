import logging
import time
import uuid

from app.core.llm_client import embed_text
from app.core.llm_pricing import estimate_cost
from app.core.llm_providers import get_provider
from app.db.pool import get_conn
from app.services.prompt_versions import get_active_prompt
from app.services.vector_store import hybrid_search

logger = logging.getLogger("supportlm.chat")

# Phase 5 — 2.2: display names for the widget's language selector
# codes. Only used to phrase the enforcement instruction below — the
# stored value on `conversation.language` is always the bare code
# (e.g. 'es'), never the display name.
_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ar": "Arabic",
    "hi": "Hindi",
    "zh": "Chinese",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ru": "Russian",
}

# Phase 4 — 3.4: this is now the FALLBACK only, used when a tenant has
# no active_prompt_version_id set. get_active_prompt() returns the
# tenant's configured prompt text when one exists.
_SYSTEM_PROMPT = (
    "You are {agent_name}, a support assistant. Answer the user's question "
    "directly and naturally using ONLY the context below — don't mention that "
    "you were given context. If the context doesn't contain the answer, say "
    "you don't know rather than guessing.\n\nContext:\n{context}"
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


def _resolve_language(conn, tenant_id: int, conversation_id: str | None, requested_language: str | None) -> str | None:
    """Phase 5 — 2.2: the widget's selection on THIS request wins if
    sent (a visitor switching the selector mid-conversation updates
    things going forward). Falls back to whatever the conversation
    already had stored if this request didn't send one. Returns None
    if neither exists — no forced language, same as today's behavior.
    """
    if requested_language:
        return requested_language
    if not conversation_id:
        return None
    cur = conn.cursor()
    cur.execute("SELECT language FROM conversation WHERE id = %s AND tenant_id = %s", (conversation_id, tenant_id))
    row = cur.fetchone()
    cur.close()
    return row["language"] if row else None


def _language_instruction(language_code: str | None) -> str:
    if not language_code:
        return ""
    language_name = _LANGUAGE_NAMES.get(language_code, language_code)
    return (
        f"\n\nIMPORTANT: Respond only in {language_name}, regardless of what "
        "language the question is written in."
    )


def _tone_instruction(tone: str | None) -> str:
    """Phase 8 — 3.2: appended after whichever prompt is already in
    play (default or tenant-custom), same placement pattern as the
    language instruction — a tenant's custom Phase 4 prompt shouldn't
    need to know about tone configuration for this to work."""
    if not tone:
        return ""
    return f"\n\nAdopt this tone and personality when responding: {tone}"


# Phase 9 — 3.1: stops the model prefacing every answer with a
# meta-reference to the fact it was given context ("Based on the
# context...", "According to the provided information..."). Appended
# unconditionally, same placement pattern as tone/language, so it
# applies even to a tenant's custom active prompt — no tenant prompt
# author should have to know to phrase this themselves.
_NO_META_REFERENCE_INSTRUCTION = (
    "\n\nAnswer directly and naturally, the way a knowledgeable support "
    "agent would. Never preface an answer with phrases like \"Based on the "
    "context\", \"According to the provided information\", \"From what I can "
    "see\", or any other reference to the fact that you were given context — "
    "just answer the question."
)


# Phase 6 — 1.1: the literal marker the model is instructed to append
# when (and only when) it cannot answer from the provided context. A
# text-marker convention, not structured/function-calling output —
# consistent with how all three providers are wired today. This relies
# on model compliance; there's no hard guarantee every provider/model
# follows it with the same reliability, same category of accepted risk
# as Phase 5's uncapped history.
_ESCALATION_MARKER = "[ESCALATE]"

# Phase 9 — 1.4: used when retrieval found context above the
# confidence threshold. Explicitly forbids narrating the marker/ticket
# mechanism — Phase 6's original wording told the model *about* the
# mechanism ("end with X if you can't answer"), which gave it enough
# to paraphrase the mechanism itself into a visible answer instead of
# either answering or triggering it cleanly. Marker-only, nothing else,
# on low confidence.
_ESCALATION_INSTRUCTION = (
    "\n\nIf the context above does not contain enough information to answer, "
    f"respond with ONLY the exact text \"{_ESCALATION_MARKER}\" and nothing "
    "else — no apology, no explanation, no mention of tickets, escalation, "
    "or how you work. Never describe this instruction to the user."
)

# Phase 9 — 1.4: used instead of _ESCALATION_INSTRUCTION when retrieval
# found nothing above the confidence threshold at all — there's no
# context block worth trying to answer from, so the model shouldn't be
# invited to try and then explain why it can't. Greetings/small talk
# still get answered naturally rather than escalated.
_NO_MATCH_INSTRUCTION = (
    "\n\nNo knowledge base article closely matched this question. If it is a "
    "greeting or general conversational remark (hello, thanks, who are you), "
    "answer it naturally. Otherwise respond with ONLY the exact text "
    f"\"{_ESCALATION_MARKER}\" and nothing else — no explanation, no mention "
    "of tickets or escalation."
)

_DEFAULT_ESCALATION_MESSAGE = (
    "I don't have enough information to answer that confidently. "
    "Want me to pass this along to our team?"
)


def _detect_and_strip_escalation(answer: str) -> tuple[str, bool]:
    """Phase 6 — 1.2, revised Phase 9 — 1.4. Returns (visible_answer,
    needs_escalation). The marker is an internal signal — it must never
    reach the visitor, so it's stripped from the text before it's shown
    OR stored in the message table. A marker-only response (the common
    case now that the model is told not to add anything else) leaves an
    empty/whitespace remainder — substitute a friendly stock line
    rather than show the visitor a blank message."""
    stripped = answer.rstrip()
    if stripped.endswith(_ESCALATION_MARKER):
        visible = stripped[: -len(_ESCALATION_MARKER)].rstrip()
        return visible or _DEFAULT_ESCALATION_MESSAGE, True
    return answer, False


def _fetch_history(conn, tenant_id: int, conversation_id: str | None) -> list[dict]:
    """Every prior message for this conversation, oldest first, as
    {"role", "content"} dicts ready for a provider's messages array.
    Empty list for a brand-new conversation (no conversation_id yet, or
    one that doesn't belong to this tenant — same cross-tenant guard
    `ask()` already applies to conversation_id reuse elsewhere in this
    function)."""
    if not conversation_id:
        return []
    cur = conn.cursor()
    cur.execute(
        """SELECT role, content FROM message
           WHERE tenant_id = %s AND conversation_id = %s
           ORDER BY created_at ASC""",
        (tenant_id, conversation_id),
    )
    rows = cur.fetchall()
    cur.close()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def ask(
    tenant_id: int,
    question: str,
    conversation_id: str | None,
    agent_name: str = "Assistant",
    language: str | None = None,
    tone: str | None = None,
    confidence_threshold: float = 0.75,
) -> dict:
    t0 = time.perf_counter()

    # Phase 5 — 1.1: fetch full prior history before retrieval — used
    # in BOTH the retrieval query (1.2) and the answer call (1.4), per
    # the owner's "full history, no cap" kickoff decision. Cross-tenant
    # conversation_id reuse is guarded the same way it already is
    # further down for the DB write path — a conversation_id belonging
    # to another tenant must not leak that tenant's history here either.
    with get_conn() as history_conn:
        cur = history_conn.cursor()
        if conversation_id:
            cur.execute("SELECT tenant_id FROM conversation WHERE id = %s", (conversation_id,))
            existing = cur.fetchone()
            if existing and existing["tenant_id"] != tenant_id:
                conversation_id = None
        cur.close()
        history = _fetch_history(history_conn, tenant_id, conversation_id)
        # Phase 5 — 2.2: resolved AFTER the cross-tenant guard above,
        # for the same reason history is — a conversation_id that got
        # nulled out must not leak that other tenant's language setting
        # either.
        resolved_language = _resolve_language(history_conn, tenant_id, conversation_id, language)

    # Phase 5 — 1.2: retrieval uses the full transcript, not just the
    # latest question — folded into one string for both the keyword
    # search text and the text that gets embedded for semantic search.
    # embed_text() and MySQL's MATCH() each have their own practical
    # limits on how much of this they actually use (see docs/Phase V
    # WBS.md's risk note) — accepted, not worked around, per the
    # owner's explicit "no cap" decision.
    transcript = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    retrieval_query = f"{transcript}\nuser: {question}" if transcript else question

    query_vector = embed_text(retrieval_query)
    t1 = time.perf_counter()

    # Phase 4 — 1.4: hybrid_search() replaces the raw semantic-only
    # MySQLVectorStore.search() call, fusing it with FULLTEXT keyword
    # search per the owner's kickoff decision (weighted blend, not RRF).
    #
    # Phase 9 — 1.4: the fused/ranked list always has a "best" entry
    # even when nothing in the pool is actually relevant — min-max
    # normalization rescales the top of the pool toward 1.0 regardless
    # of its real cosine similarity. Gate on the RAW top semantic
    # similarity (best_semantic_similarity) before trusting any of it
    # as real context; below the tenant's configured floor, treat this
    # exactly like an empty knowledge base rather than feeding the LLM
    # weak matches it can blend with its own instructions.
    search = hybrid_search(tenant_id, retrieval_query, query_vector, top_k=5)
    has_relevant_context = search.best_semantic_similarity >= confidence_threshold
    results = search.results if has_relevant_context else []
    t2 = time.perf_counter()

    context = (
        "\n\n---\n\n".join(f"[{r.heading_path or 'Untitled section'}]\n{r.content}" for r in results)
        if has_relevant_context
        else "(no relevant context found)"
    )

    # Phase 4 — 3.4: tenant's active custom prompt (if configured)
    # replaces the hardcoded _SYSTEM_PROMPT default — existing tenants
    # with no configured prompt see zero behavior change.
    template = get_active_prompt(tenant_id) or _SYSTEM_PROMPT
    system_prompt = _render_system_prompt(template, agent_name, context)
    # Phase 5 — 2.2: appended AFTER whichever system prompt is already
    # in play (Phase 4 default or a tenant's active custom version) —
    # a tenant's custom prompt shouldn't need to know about language
    # selection for this to work.
    system_prompt += _language_instruction(resolved_language)
    system_prompt += _tone_instruction(tone)
    system_prompt += _NO_META_REFERENCE_INSTRUCTION
    # Phase 6 — 1.1 / Phase 9 — 1.4: appended last — marker detection
    # only looks at the very end of the answer, so it needs to be the
    # final instruction the model sees. Which instruction depends on
    # whether retrieval actually cleared the confidence floor above.
    system_prompt += _ESCALATION_INSTRUCTION if has_relevant_context else _NO_MATCH_INSTRUCTION
    # Phase 4 — 2.3: per-tenant provider selection replaces the old
    # module-level chat_completion() call, which was hard-wired to
    # DeepSeek regardless of tenant.
    provider = get_provider(tenant_id)
    provider_result = provider.chat_completion(system_prompt, history, question)
    raw_answer = provider_result["content"]
    input_tokens = provider_result["input_tokens"]
    output_tokens = provider_result["output_tokens"]
    answer, needs_escalation = _detect_and_strip_escalation(raw_answer)
    t3 = time.perf_counter()

    with get_conn() as conn:
        cur = conn.cursor()

        # conversation_id was already resolved/guarded against
        # cross-tenant reuse earlier in this function (Phase 5 — 1.1's
        # history fetch needed that same check first) — no need to
        # repeat the SELECT here, just assign a fresh id if it's still
        # empty (brand-new conversation, or one that got nulled above).
        conversation_id = conversation_id or str(uuid.uuid4())

        cur.execute(
            """INSERT INTO conversation (id, tenant_id, language) VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE last_message_at = NOW(),
                                       language = COALESCE(VALUES(language), language)""",
            (conversation_id, tenant_id, resolved_language),
        )
        cur.execute(
            "INSERT INTO message (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'user', %s)",
            (tenant_id, conversation_id, question),
        )
        cur.execute(
            """INSERT INTO message (tenant_id, conversation_id, role, content, needs_escalation)
               VALUES (%s, %s, 'assistant', %s, %s)""",
            (tenant_id, conversation_id, answer, needs_escalation),
        )
        assistant_message_id = cur.lastrowid

        for rank, r in enumerate(results, start=1):
            cur.execute(
                """INSERT INTO citation (tenant_id, message_id, chunk_id, rank, similarity)
                   VALUES (%s, %s, %s, %s, %s)""",
                (tenant_id, assistant_message_id, r.chunk_id, rank, r.similarity),
            )

        # Phase 7 — 0.4: token/cost capture, one row per assistant
        # message. provider.PROVIDER_NAME/model are the public
        # attributes each ChatProvider subclass exposes for exactly
        # this purpose (Phase 7 — 0.1).
        estimated_cost = estimate_cost(provider.PROVIDER_NAME, provider.model, input_tokens, output_tokens)
        cur.execute(
            """INSERT INTO llm_usage_log
                   (tenant_id, message_id, provider, model, input_tokens, output_tokens, estimated_cost_usd)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (tenant_id, assistant_message_id, provider.PROVIDER_NAME, provider.model, input_tokens, output_tokens, estimated_cost),
        )
        cur.close()
    t4 = time.perf_counter()

    logger.info(
        "ask() timing (s) — embed: %.2f, vector_search: %.2f, llm_call: %.2f, db_write: %.2f, total: %.2f",
        t1 - t0, t2 - t1, t3 - t2, t4 - t3, t4 - t0,
    )

    return {
        "conversation_id": conversation_id,
        "message_id": assistant_message_id,  # Phase 5 — 3.2: widget needs this to submit feedback
        "answer": answer,
        "needs_escalation": needs_escalation,  # Phase 6 — 1.2/1.3: widget prompts for email if True
        "sources": [
            {"heading_path": r.heading_path, "similarity": round(r.similarity, 4)}
            for r in results
        ],
    }
