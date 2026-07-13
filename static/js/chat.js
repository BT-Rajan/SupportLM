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
      const data = await res.json();
      if (!res.ok) {
        appendMessage("assistant", data.detail || "Something went wrong. Please try again.");
        return;
      }
      conversationId = data.conversation_id;
      appendMessage("assistant", data.answer);
      appendSources(data.sources);
    } catch (err) {
      appendMessage("assistant", "Something went wrong. Please try again.");
    } finally {
      input.disabled = false;
      input.focus();
    }
  });
})();
