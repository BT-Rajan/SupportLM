# Phase 5 WBS — Conversation Experience

> Scope source: `docs/MASTER_PROMPT.md` Section 3, "Phase 5". Nothing
> here expands that scope; this file breaks it into buildable, ordered
> rounds the way `docs/Phase I-IV WBS.md` did for their phases.

Phase 5 scope, verbatim from the master prompt: multi-turn memory
(follow-up questions use prior turns as context, not independent
retrieval per message). Multi-language support. Thumbs up/down
feedback per answer (built here because Phase 6 analytics depends on
it).

## Owner decisions confirmed at kickoff

- **1.0 multi-turn memory**: **full conversation history, no cap**, used
  in *both* retrieval and the answer call — not a capped last-N window,
  not a separate query-condensing/rewriting LLM call first. The entire
  prior transcript of the conversation is folded into the retrieval
  query text/vector AND passed as real conversation turns to the chat
  provider.
- **2.0 multi-language**: an **explicit language selector in the chat
  widget** — the visitor picks a language up front (or mid-conversation
  to switch), and replies are forced into that language regardless of
  what language the visitor actually types in. Not auto-detection.
- **3.0 feedback**: **simple thumbs up/down, anonymous, no comment
  field.** The "let the visitor change their vote afterward" option was
  explicitly *not* chosen — see 3.1 below for what that means for the
  schema/endpoint.

## A real risk worth flagging before 1.1 — "no cap" has three separate ceilings

The owner's decision is implemented literally, but it's worth being
explicit that "no cap" runs into three independent limits that this
phase does **not** work around, since none were in scope to fix:

1. **Embedding truncation**: `sentence-transformers`'
   `all-MiniLM-L6-v2` (the configured `EMBEDDING_MODEL_NAME`) has a
   256-token input ceiling — a long transcript folded into the
   retrieval query gets silently truncated by the model itself before
   `embed_text()` ever returns a vector. Retrieval quality on a long
   conversation degrades to "whatever fits in the first ~256 tokens,"
   not a hard failure.
2. **MySQL FULLTEXT practical limits**: `MATCH() AGAINST()` in natural
   language mode still runs on an arbitrarily long query string, but
   relevance scoring quality degrades as query length grows (this is a
   MySQL/MariaDB characteristic, not a hard cap) — flagged for
   awareness, not a bug to fix here.
3. **Provider context windows**: DeepSeek/OpenAI/Anthropic all have
   real token ceilings on the request itself. A long enough
   conversation eventually gets a 400-class error back from whichever
   provider a tenant has configured (Phase 4's `httpx.HTTPStatusError`
   handling in `app/api/chat.py`'s `post_chat` already surfaces this as
   a 502 with the provider's real error text — nothing new needed
   there, it already doesn't fail silently).

None of these are fixed by this phase — "no cap" was the explicit
decision, and capping/summarizing history is exactly the kind of
follow-up work that decision rules out for now. Noted here so a future
session doesn't mistake a long-conversation degradation for a bug this
phase was supposed to prevent.

## Dependency order

1.0 (multi-turn memory) and 3.0 (feedback) both touch
`app/services/chat.py`'s `ask()` and the `message` table, so 1.0 goes
first — 3.0's feedback endpoint just needs a `message_id` to attach to,
which already exists regardless of 1.0's changes, so there's no reason
to block 3.0 on 1.0 landing first beyond doing the bigger change before
the smaller one. 2.0 (language) is independent of both — it only
touches the system prompt and a new `conversation.language` column —
and could be built in any order, sequenced second here only because it
touches the same `ask()` function 1.0 just finished editing (same
"touch the shared function once, not three times" reasoning Phase 4's
WBS used for its own 1.0/2.0/3.0 ordering).

## 1.0 Multi-turn Memory

- **1.1 Fetch history**: `app/services/chat.py` — before calling
  `hybrid_search()`, fetch every prior `message` row for this
  `conversation_id` (ordered by `created_at ASC`), if a
  `conversation_id` was supplied and belongs to this tenant (reusing
  the existing cross-tenant `conversation_id` guard already in `ask()`
  — a new conversation has no history to fetch, so this is a no-op for
  the first turn).
- **1.2 Retrieval uses full history**: the text passed to
  `hybrid_search()`'s keyword search AND the vector passed for semantic
  search are both built from the **full transcript** (every prior
  user+assistant turn, in order, concatenated) plus the current
  question — not the current question alone. `embed_text()` and
  MySQL's `MATCH()` will each hit their own practical limits on a long
  transcript per the risk note above; that degradation is accepted, not
  worked around.
- **1.3 `ChatProvider` protocol gains real multi-turn support**:
  `app/core/llm_providers.py`'s `chat_completion(system_prompt,
  user_message)` becomes `chat_completion(system_prompt, history,
  user_message)`, where `history` is an ordered list of
  `{"role": "user"|"assistant", "content": str}` turns. Each provider
  builds its *own* multi-turn shape (DeepSeek/OpenAI: history entries
  appended to the `messages` array between the system message and the
  new user message; Anthropic: same idea, but `system` stays a
  top-level field per its existing shape, only `messages` gets the
  history entries) — no shared base class forcing one shape onto all
  three, same reasoning Phase 4's 2.2 used for the initial
  single-turn versions.
- **1.4 Wire into `ask()`**: `app/services/chat.py` passes the fetched
  history (formatted as role/content dicts, not raw `message` rows) to
  `provider.chat_completion(system_prompt, history, question)`.

## 2.0 Multi-language Support

- **2.1 Schema**: `migrations/018_conversation_language.sql` adds
  `conversation.language` (`VARCHAR(10) NULL`, e.g. `'en'`, `'es'`,
  `'ar'` — NULL means no explicit selection yet, same "explicit
  override, no forced default" contract as every other Phase 1-4
  nullable config column). Set on first message of a conversation from
  whatever the widget sends; a visitor switching the selector
  mid-conversation updates it going forward (not retroactively
  relabeling past turns).
- **2.2 Enforce in the answer call**: `app/services/chat.py`'s system
  prompt gets an appended, non-overridable instruction — *"Respond
  only in {language_name}, regardless of what language the question is
  written in"* — resolved from the conversation's `language` column
  (or the widget's selection on a brand-new conversation with no row
  yet). This is appended after whatever system prompt text is already
  in play (the Phase 4 default or a tenant's active custom version),
  not merged into either — a tenant's custom prompt shouldn't need to
  know about language selection to have it work.
- **2.3 Widget UI**: a language `<select>` in `chat.html`'s header
  (same area as the existing transcript-email button), `chat.js` sends
  the selected code as a new `language` field on `ChatRequest`.
  Defaults to English on first load; persisted in the browser via
  `localStorage` so a returning visitor doesn't have to re-pick every
  page load (this is the real deployed chat widget, not a sandboxed
  Claude artifact — `localStorage` is a normal, correct choice here,
  not the restricted case that applies inside this session's own
  Artifacts tooling).
- **2.4 `ChatRequest` gains `language`**: `app/api/chat.py`'s
  `ChatRequest` gets an optional `language: str | None` field, passed
  through to `ask()`.

## 3.0 Thumbs Up/Down Feedback

- **3.1 Schema**: `migrations/019_message_feedback.sql` adds
  `message_feedback` (`message_id` **UNIQUE**, `tenant_id`, `rating
  ENUM('up','down')`, `created_at`). The UNIQUE constraint is the
  direct consequence of the kickoff decision: "let the visitor change
  their vote" was explicitly *not* chosen, so a second feedback
  submission for the same `message_id` is rejected outright (409), not
  silently overwritten and not accepted as a revision — one vote per
  message, permanently.
- **3.2 Endpoint**: `POST /api/chat/{message_id}/feedback`
  (`app/api/chat.py`, anonymous — same auth-free surface as `post_chat`
  itself), body `{"rating": "up"|"down"}`. Validates the message
  belongs to this tenant and is an **assistant** message (a visitor
  can't rate their own question) before inserting; a duplicate
  submission for an already-rated message returns 409, not a silent
  success.
- **3.3 Widget UI**: thumbs-up/down icon pair under each assistant
  message bubble in `chat.js`, disabled immediately after a vote is
  cast (client-side reflects the "no re-vote" rule the same round it's
  enforced server-side, rather than letting a visitor click again and
  only finding out from a 409).

## 4.0 Testing & Validation

Same shape as Phases 2-4: round-by-round tests land alongside each
round above, DB-gated tests skip cleanly with no DB reachable, plus a
full-suite pass on a freshly rebuilt database once 1.0-3.0 are done,
same discipline as every phase so far.

## 5.0 Documentation & Handoff

`docs/STATUS.md` updated per round, same as every prior phase. No new
admin-facing surface this phase (all three sections are
visitor/widget-facing, not admin-console-facing), so no new admin UI
backlog item to add alongside the existing one.
