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

  const transcriptToggle = document.getElementById("transcript-toggle");
  const transcriptPanel = document.getElementById("transcript-panel");
  const transcriptEmail = document.getElementById("transcript-email");
  const transcriptSend = document.getElementById("transcript-send");
  const transcriptCancel = document.getElementById("transcript-cancel");
  const transcriptStatus = document.getElementById("transcript-status");

  // Phase 5 — 2.3: language selector. Persisted per-browser via
  // localStorage (this is the real deployed widget, not a sandboxed
  // artifact — localStorage is the correct, normal choice here) so a
  // returning visitor doesn't have to re-pick every page load. Storage
  // key is scoped by tenant slug since one browser may visit multiple
  // tenants' widgets.
  const languageSelect = document.getElementById("language-select");
  const LANGUAGE_STORAGE_KEY = "supportlm-language-" + window.TENANT_SLUG;

  (function restoreLanguage() {
    try {
      const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
      if (saved) languageSelect.value = saved;
    } catch (err) {
      // localStorage unavailable (private browsing, disabled, etc.) —
      // fall back silently to the selector's default value.
    }
  })();

  languageSelect.addEventListener("change", function () {
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, languageSelect.value);
    } catch (err) {
      // Same silent fallback as above — persistence is a nicety, not
      // required for the selector to keep working this session.
    }
  });

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

  function attachEscalation(wrap, messageId) {
    // Phase 6 — 1.3: shown as its own inline panel under the assistant
    // bubble, not folded into the meta row the way feedback/sources
    // are — this needs an email input and a submit action, not just an
    // icon click, so it gets more visual room.
    const panel = document.createElement("div");
    panel.className = "escalation-panel";

    const label = document.createElement("div");
    label.className = "escalation-label";
    label.textContent = "I couldn't fully answer that. Want a team member to follow up? Enter your email:";
    panel.appendChild(label);

    const row = document.createElement("div");
    row.className = "escalation-row";

    const emailInput = document.createElement("input");
    emailInput.type = "email";
    emailInput.className = "escalation-email";
    emailInput.placeholder = "you@example.com";

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "escalation-submit";
    submitBtn.textContent = "Submit";

    const status = document.createElement("div");
    status.className = "escalation-status";

    row.appendChild(emailInput);
    row.appendChild(submitBtn);
    panel.appendChild(row);
    panel.appendChild(status);
    wrap.appendChild(panel);

    async function submit() {
      const email = emailInput.value.trim();
      if (!email) {
        status.textContent = "Please enter an email address.";
        status.className = "escalation-status error";
        return;
      }
      submitBtn.disabled = true;
      emailInput.disabled = true;
      status.textContent = "";

      try {
        const res = await fetch(TENANT_BASE + "/api/chat/" + messageId + "/escalate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email }),
        });
        const rawBody = await res.text();
        let data = null;
        try {
          data = rawBody ? JSON.parse(rawBody) : null;
        } catch (parseErr) {
          status.textContent = "Server error (" + res.status + ").";
          status.className = "escalation-status error";
          submitBtn.disabled = false;
          emailInput.disabled = false;
          return;
        }

        if (!res.ok) {
          status.textContent = (data && data.detail) || "Could not create a support request.";
          status.className = "escalation-status error";
          submitBtn.disabled = false;
          emailInput.disabled = false;
          return;
        }

        status.textContent = "Support request " + data.sr_number + " created — check your email.";
        status.className = "escalation-status success";
      } catch (err) {
        status.textContent = "Network error: could not reach the server.";
        status.className = "escalation-status error";
        submitBtn.disabled = false;
        emailInput.disabled = false;
      }
    }

    submitBtn.addEventListener("click", submit);
    emailInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
  }

  function attachFeedback(meta, messageId) {
    // Phase 5 — 3.3: simple thumbs up/down, anonymous, no comment
    // field. Disabled immediately on click — the server enforces "no
    // re-voting" with a 409, but the widget shouldn't wait for that
    // round-trip to reflect the same rule; a visitor shouldn't be able
    // to click twice and only find out the second click did nothing.
    if (!messageId) return;

    const bar = document.createElement("div");
    bar.className = "feedback-bar";

    const up = document.createElement("button");
    up.type = "button";
    up.className = "feedback-btn feedback-up";
    up.setAttribute("aria-label", "Helpful");
    up.textContent = "\u{1F44D}";

    const down = document.createElement("button");
    down.type = "button";
    down.className = "feedback-btn feedback-down";
    down.setAttribute("aria-label", "Not helpful");
    down.textContent = "\u{1F44E}";

    function submit(rating, clicked, other) {
      clicked.disabled = true;
      other.disabled = true;
      clicked.classList.add("feedback-selected");
      fetch(TENANT_BASE + "/api/chat/" + messageId + "/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: rating }),
      }).catch(function () {
        // Best-effort — a failed feedback submission shouldn't disrupt
        // the chat experience with an error message of its own.
      });
    }

    up.addEventListener("click", function () {
      submit("up", up, down);
    });
    down.addEventListener("click", function () {
      submit("down", down, up);
    });

    bar.appendChild(up);
    bar.appendChild(down);
    meta.appendChild(bar);
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

  // WBS 4.3: the button starts `disabled` in chat.html — there's no
  // conversation to email until the first exchange completes. Called
  // once conversationId is first set inside sendQuestion() below.
  function enableTranscriptButton() {
    transcriptToggle.disabled = false;
    transcriptToggle.title = "Email me this conversation";
  }

  function setTranscriptStatus(text, kind) {
    transcriptStatus.textContent = text;
    transcriptStatus.classList.remove("success", "error");
    if (kind) transcriptStatus.classList.add(kind);
    transcriptStatus.hidden = !text;
  }

  function closeTranscriptPanel() {
    transcriptPanel.hidden = true;
    transcriptToggle.setAttribute("aria-expanded", "false");
  }

  transcriptToggle.addEventListener("click", function () {
    const isOpen = !transcriptPanel.hidden;
    if (isOpen) {
      closeTranscriptPanel();
      return;
    }
    transcriptPanel.hidden = false;
    transcriptToggle.setAttribute("aria-expanded", "true");
    setTranscriptStatus("");
    transcriptEmail.focus();
  });

  transcriptCancel.addEventListener("click", function () {
    closeTranscriptPanel();
    setTranscriptStatus("");
  });

  async function sendTranscript() {
    const email = transcriptEmail.value.trim();
    if (!email) {
      setTranscriptStatus("Enter an email address first.", "error");
      return;
    }
    if (!conversationId) {
      setTranscriptStatus("Start a conversation first.", "error");
      return;
    }

    transcriptSend.disabled = true;
    transcriptEmail.disabled = true;
    setTranscriptStatus("Sending…");

    try {
      const res = await fetch(TENANT_BASE + "/api/chat/transcript", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, email: email }),
      });

      // Same defensive parse as sendQuestion() — the server always
      // returns JSON, but don't throw into a blank error if that
      // ever isn't true.
      const rawBody = await res.text();
      let data = null;
      try {
        data = rawBody ? JSON.parse(rawBody) : null;
      } catch (parseErr) {
        setTranscriptStatus("Server error (" + res.status + ").", "error");
        return;
      }

      if (!res.ok) {
        setTranscriptStatus((data && data.detail) || "Could not send the transcript.", "error");
        return;
      }

      setTranscriptStatus("Sent! Check your inbox.", "success");
      transcriptEmail.value = "";
      setTimeout(closeTranscriptPanel, 2000);
    } catch (err) {
      setTranscriptStatus("Network error: could not reach the server.", "error");
    } finally {
      transcriptSend.disabled = false;
      transcriptEmail.disabled = false;
    }
  }

  transcriptSend.addEventListener("click", sendTranscript);
  transcriptEmail.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      sendTranscript();
    }
  });

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
        body: JSON.stringify({
          question: question,
          conversation_id: conversationId,
          language: languageSelect.value,
        }),
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
      if (conversationId) enableTranscriptButton();
      const { wrap, meta } = appendMessage("assistant", data.answer);
      attachSources(meta, data.sources);
      attachFeedback(meta, data.message_id);
      if (data.needs_escalation) attachEscalation(wrap, data.message_id);
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
