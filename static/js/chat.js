// Minimal chat widget — no framework, no build step.
(function () {
  let conversationId = null;

  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");

  function appendMessage(role, text) {
    const el = document.createElement("div");
    el.className = "msg msg-" + role;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  function appendSources(sources) {
    if (!sources || sources.length === 0) return;
    const el = document.createElement("div");
    el.className = "msg-sources";
    el.textContent = "Sources: " + sources.map((s) => s.heading_path || "Untitled").join(", ");
    log.appendChild(el);
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    const question = input.value.trim();
    if (!question) return;

    appendMessage("user", question);
    input.value = "";
    input.disabled = true;

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, conversation_id: conversationId }),
      });

      // Parse the body defensively: the server always returns JSON now,
      // but if something upstream (proxy, unexpected route, etc.) ever
      // returns plain text again, we still want to show *that* text
      // instead of throwing and falling into the generic catch below.
      const rawBody = await res.text();
      let data = null;
      try {
        data = rawBody ? JSON.parse(rawBody) : null;
      } catch (parseErr) {
        appendMessage(
          "assistant",
          "Server error (" + res.status + "): " + (rawBody || "no response body").slice(0, 300)
        );
        return;
      }

      if (!res.ok) {
        appendMessage("assistant", (data && data.detail) || "Request failed with status " + res.status + ".");
        return;
      }

      conversationId = data.conversation_id;
      appendMessage("assistant", data.answer);
      appendSources(data.sources);
    } catch (err) {
      appendMessage("assistant", "Network error: could not reach the server. " + (err && err.message ? err.message : ""));
    } finally {
      input.disabled = false;
      input.focus();
    }
  });
})();
