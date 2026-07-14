// Minimal chat widget — no framework, no build step.
(function () {
  let conversationId = null;
  let sourceIdCounter = 0;

  // Set by the server-rendered page (see templates/chat.html) so this
  // widget knows which tenant it's talking to (WBS 3.1: path-param
  // tenant resolution — every API call is scoped under /t/{slug}/).
  const TENANT_BASE = "/t/" + window.TENANT_SLUG;

  const log = document.getElementById("chat-log");
  const welcome = document.getElementById("welcome");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = form.querySelector(".composer-send");

  function formatTime(date) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function dismissWelcome() {
    if (welcome) welcome.remove();
  }

  function appendMessage(role, text) {
    const row = document.createElement("div");
    row.className = "row row-" + role;

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap";

    const bubble = document.createElement("div");
    bubble.className = "msg msg-" + role;
    bubble.textContent = text;
    wrap.appendChild(bubble);

    const meta = document.createElement("div");
    meta.className = "meta-row";
    const time = document.createElement("span");
    time.className = "timestamp";
    time.textContent = formatTime(new Date());
    meta.appendChild(time);
    wrap.appendChild(meta);

    row.appendChild(wrap);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return { row, wrap, meta };
  }

  function attachSources(meta, sources) {
    if (!sources || sources.length === 0) return;
    sourceIdCounter += 1;
    const listId = "sources-" + sourceIdCounter;

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "sources-toggle";
    toggle.textContent = sources.length + (sources.length === 1 ? " source" : " sources");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", listId);
    meta.appendChild(toggle);

    const list = document.createElement("div");
    list.className = "sources-list";
    list.id = listId;
    const ul = document.createElement("ul");
    sources.forEach((s) => {
      const li = document.createElement("li");
      li.textContent = s.heading_path || "Untitled section";
      ul.appendChild(li);
    });
    list.appendChild(ul);
    meta.parentElement.appendChild(list);

    toggle.addEventListener("click", function () {
      const isOpen = list.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "row row-assistant";
    row.id = "typing-row";
    const bubble = document.createElement("div");
    bubble.className = "typing-bubble";
    bubble.innerHTML = "<span></span><span></span><span></span>";
    row.appendChild(bubble);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  function hideTyping() {
    const row = document.getElementById("typing-row");
    if (row) row.remove();
  }

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }

  input.addEventListener("input", autoResize);

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      input.value = chip.textContent;
      form.requestSubmit();
    });
  });

  async function sendQuestion(question) {
    dismissWelcome();
    appendMessage("user", question);
    input.value = "";
    autoResize();
    input.disabled = true;
    sendBtn.disabled = true;
    showTyping();

    try {
      const res = await fetch(TENANT_BASE + "/api/chat", {
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
        hideTyping();
        appendMessage(
          "error",
          "Server error (" + res.status + "): " + (rawBody || "no response body").slice(0, 300)
        );
        return;
      }

      hideTyping();

      if (!res.ok) {
        appendMessage("error", (data && data.detail) || "Request failed with status " + res.status + ".");
        return;
      }

      conversationId = data.conversation_id;
      const { meta } = appendMessage("assistant", data.answer);
      attachSources(meta, data.sources);
    } catch (err) {
      hideTyping();
      appendMessage("error", "Network error: could not reach the server. " + (err && err.message ? err.message : ""));
    } finally {
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    sendQuestion(question);
  });
})();
