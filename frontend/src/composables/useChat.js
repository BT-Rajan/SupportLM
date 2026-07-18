import { reactive, ref } from "vue";

/**
 * All network I/O for the widget lives here, isolated from rendering.
 * Endpoints and payload shapes match app/api/chat.py exactly:
 *   POST   /t/{slug}/api/chat                 {question, conversation_id, language}
 *   POST   /t/{slug}/api/chat/transcript       {conversation_id, email}
 *   POST   /t/{slug}/api/chat/{id}/feedback    {rating}
 *   POST   /t/{slug}/api/chat/{id}/escalate    {email}
 */
export function useChat(tenantSlug) {
  const base = `/t/${tenantSlug}/api/chat`;
  const messages = reactive([]);
  const conversationId = ref(null);
  const sending = ref(false);
  const limitWarning = ref(null);
  let nextId = 1;

  async function parseResponse(res) {
    const raw = await res.text();
    let data = null;
    try {
      data = raw ? JSON.parse(raw) : null;
    } catch {
      return { ok: false, status: res.status, data: null, malformed: true, raw };
    }
    return { ok: res.ok, status: res.status, data, malformed: false, raw };
  }

  async function sendQuestion(question, language) {
    const userMsg = { id: nextId++, role: "user", text: question, ts: new Date() };
    messages.push(userMsg);
    sending.value = true;

    const pendingId = nextId++;
    messages.push({ id: pendingId, role: "pending", ts: new Date() });

    try {
      const res = await fetch(base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: conversationId.value,
          language,
        }),
      });
      const { ok, status, data, malformed, raw } = await parseResponse(res);
      const idx = messages.findIndex((m) => m.id === pendingId);

      if (malformed) {
        messages.splice(idx, 1, {
          id: pendingId,
          role: "error",
          text: `Server error (${status}): ${(raw || "no response body").slice(0, 300)}`,
        });
        return;
      }
      if (!ok) {
        messages.splice(idx, 1, {
          id: pendingId,
          role: "error",
          text: (data && data.detail) || `Request failed with status ${status}.`,
        });
        return;
      }

      conversationId.value = data.conversation_id;
      limitWarning.value = data.limit_warning || null;
      messages.splice(idx, 1, {
        id: pendingId,
        role: "assistant",
        text: data.answer,
        messageId: data.message_id,
        sources: data.sources || [],
        needsEscalation: !!data.needs_escalation,
        ts: new Date(),
      });
    } catch (err) {
      const idx = messages.findIndex((m) => m.id === pendingId);
      const text = "Network error: could not reach the server. " + (err && err.message ? err.message : "");
      if (idx !== -1) messages.splice(idx, 1, { id: pendingId, role: "error", text });
      else messages.push({ id: pendingId, role: "error", text });
    } finally {
      sending.value = false;
    }
  }

  async function submitFeedback(messageId, rating) {
    try {
      await fetch(`${base}/${messageId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
      });
    } catch {
      // Best-effort, matches prior behavior: a failed vote shouldn't
      // interrupt the conversation with an error of its own.
    }
  }

  async function submitEscalation(messageId, email) {
    const res = await fetch(`${base}/${messageId}/escalate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const { ok, data } = await parseResponse(res);
    if (!ok) throw new Error((data && data.detail) || "Could not create a support request.");
    return data;
  }

  async function sendTranscript(email) {
    if (!conversationId.value) throw new Error("Start a conversation first.");
    const res = await fetch(`${base}/transcript`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId.value, email }),
    });
    const { ok, data } = await parseResponse(res);
    if (!ok) throw new Error((data && data.detail) || "Could not send the transcript.");
    return data;
  }

  return {
    messages,
    conversationId,
    sending,
    limitWarning,
    sendQuestion,
    submitFeedback,
    submitEscalation,
    sendTranscript,
  };
}
