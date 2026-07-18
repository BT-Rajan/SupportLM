// Admin dashboard — no framework, no build step.
(function () {
  const loginView = document.getElementById("login-view");
  const dashboardView = document.getElementById("dashboard-view");
  const sessionLoading = document.getElementById("session-loading");

  // Set by the server-rendered page (see templates/admin.html) so this
  // dashboard knows which tenant it's managing (WBS 3.1 Phase 2: path-param
  // tenant resolution — every API call is scoped under /t/{slug}/).
  const TENANT_BASE = "/t/" + window.TENANT_SLUG;

  const REVIEW_STATES = ["draft", "review", "published"];

  async function api(path, options = {}) {
    const res = await fetch(TENANT_BASE + path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    if (res.status === 401) {
      showLogin();
      throw new Error("Not authenticated");
    }
    return res;
  }

  function showLogin() {
    sessionLoading.hidden = true;
    loginView.hidden = false;
    dashboardView.hidden = true;
  }

  function showDashboard() {
    sessionLoading.hidden = true;
    loginView.hidden = true;
    dashboardView.hidden = false;
    loadCategories();
    loadSyncSources();
    loadDuplicateFlags();
    loadDocuments();
    loadAnalytics();
    loadAuditLog();
    loadAgentConfig();
    loadLlmConfig();
    loadSupportConfig();
    loadPromptVersions();
    loadApiKeys();
  }

  // --- Login ---
  document.getElementById("login-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const email = document.getElementById("login-email").value;
    const password = document.getElementById("login-password").value;
    const errorEl = document.getElementById("login-error");
    errorEl.hidden = true;
    const res = await fetch(TENANT_BASE + "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (res.ok) {
      showDashboard();
    } else {
      errorEl.textContent = "Invalid email or password.";
      errorEl.hidden = false;
    }
  });

  document.getElementById("logout-btn").addEventListener("click", async function () {
    await fetch(TENANT_BASE + "/api/auth/logout", { method: "POST" });
    showLogin();
  });

  // --- Categories ---
  async function loadCategories() {
    const res = await api("/api/categories");
    const categories = await res.json();

    const list = document.getElementById("category-list");
    const empty = document.getElementById("category-empty");
    list.innerHTML = "";
    empty.hidden = categories.length > 0;

    const select = document.getElementById("upload-category");
    select.innerHTML = '<option value="">No category</option>';

    categories.forEach((c) => {
      const li = document.createElement("li");
      const nameSpan = document.createElement("span");
      nameSpan.textContent = c.name;
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.textContent = "Delete";
      delBtn.className = "btn-danger";
      delBtn.onclick = async () => {
        await api(`/api/categories/${c.id}`, { method: "DELETE" });
        loadCategories();
      };
      li.appendChild(nameSpan);
      li.appendChild(delBtn);
      list.appendChild(li);

      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name;
      select.appendChild(opt);
    });
  }

  document.getElementById("category-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const name = document.getElementById("category-name").value.trim();
    if (!name) return;
    await api("/api/categories", { method: "POST", body: JSON.stringify({ name }) });
    document.getElementById("category-name").value = "";
    loadCategories();
  });

  // --- Documents ---
  function statusBadge(d) {
    if (d.status === "error") {
      const msg = (d.error_message || "").replace(/"/g, "&quot;");
      return `<span class="badge badge-error" title="${msg}">error</span>`;
    }
    return `<span class="badge badge-draft">${d.status}</span>`;
  }

  function reviewStateSelect(d) {
    // WBS 1.2: editor+ can move a document through every state, in
    // either direction — a plain select reflects that directly rather
    // than implying a forced linear draft->review->published order.
    const options = REVIEW_STATES.map(
      (s) => `<option value="${s}" ${s === d.review_state ? "selected" : ""}>${s}</option>`
    ).join("");
    return `<select class="review-select" data-review-id="${d.id}">${options}</select>`;
  }

  async function loadDocuments() {
    const res = await api("/api/documents");
    const docs = await res.json();
    const tbody = document.querySelector("#document-table tbody");
    const empty = document.getElementById("document-empty");
    tbody.innerHTML = "";
    empty.hidden = docs.length > 0;

    docs.forEach((d) => {
      const tr = document.createElement("tr");
      const retryBtn = d.status !== "ready" ? `<button type="button" class="btn-ghost" data-retry-id="${d.id}">Retry</button>` : "";
      const delBtn = `<button type="button" class="btn-danger" data-id="${d.id}">Delete</button>`;
      tr.innerHTML = `<td>${d.title}</td><td>${statusBadge(d)}</td><td>${reviewStateSelect(d)}</td><td><div class="actions-cell">${retryBtn}${delBtn}</div></td>`;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll("button.btn-danger").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/documents/${btn.dataset.id}`, { method: "DELETE" });
        loadDocuments();
      });
    });
    tbody.querySelectorAll("button[data-retry-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/documents/${btn.dataset.retryId}/reindex`, { method: "POST" });
        loadDocuments();
      });
    });
    tbody.querySelectorAll("select[data-review-id]").forEach((sel) => {
      sel.addEventListener("change", async () => {
        await api(`/api/documents/${sel.dataset.reviewId}/review-state`, {
          method: "POST",
          body: JSON.stringify({ state: sel.value }),
        });
        // No full reload needed — the select already reflects the new
        // value the user picked, and nothing else in the row depends
        // on review_state.
      });
    });
  }

  // --- Website sync (WBS 2.0) ---
  async function loadSyncSources() {
    const res = await api("/api/documents/sync-sources");
    const sources = await res.json();

    const list = document.getElementById("sync-source-list");
    const empty = document.getElementById("sync-source-empty");
    list.innerHTML = "";
    empty.hidden = sources.length > 0;

    sources.forEach((s) => {
      const li = document.createElement("li");
      const info = document.createElement("span");
      const synced = s.last_synced_at ? `last synced ${s.last_synced_at}` : "not yet synced";
      info.textContent = `${s.url} — ${synced}`;
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.textContent = "Remove";
      delBtn.className = "btn-danger";
      delBtn.onclick = async () => {
        await api(`/api/documents/sync-sources/${s.id}`, { method: "DELETE" });
        loadSyncSources();
      };
      li.appendChild(info);
      li.appendChild(delBtn);
      list.appendChild(li);
    });
  }

  document.getElementById("sync-source-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const input = document.getElementById("sync-source-url");
    const url = input.value.trim();
    if (!url) return;
    const res = await api("/api/documents/sync-sources", { method: "POST", body: JSON.stringify({ url }) });
    if (res.ok) input.value = "";
    loadSyncSources();
  });

  document.getElementById("sync-now-btn").addEventListener("click", async function () {
    const btn = document.getElementById("sync-now-btn");
    const statusEl = document.getElementById("sync-now-status");
    btn.disabled = true;
    statusEl.hidden = false;
    statusEl.textContent = "Syncing…";

    const res = await api("/api/documents/sync-sources/sync-now", { method: "POST" });
    const results = await res.json();

    const ingested = results.filter((r) => r.status === "ingested").length;
    const unchanged = results.filter((r) => r.status === "unchanged").length;
    const errors = results.filter((r) => r.status.startsWith("error")).length;
    statusEl.textContent = `Done — ${ingested} updated, ${unchanged} unchanged, ${errors} failed.`;

    btn.disabled = false;
    loadSyncSources();
    loadDocuments();
  });

  // --- Duplicate content review (WBS 3.0) ---
  async function loadDuplicateFlags() {
    const res = await api("/api/documents/duplicate-flags");
    const flags = await res.json();

    const list = document.getElementById("duplicate-flag-list");
    const empty = document.getElementById("duplicate-flag-empty");
    list.innerHTML = "";
    empty.hidden = flags.length > 0;

    flags.forEach((f) => {
      const li = document.createElement("li");
      const info = document.createElement("span");
      const pct = Math.round(f.similarity * 100);
      info.textContent = `[${f.source}] "${f.label_a}" (${f.title_a}) \u2194 "${f.label_b}" (${f.title_b}) — ${pct}% similar`;
      const resolveBtn = document.createElement("button");
      resolveBtn.type = "button";
      resolveBtn.textContent = "Dismiss";
      resolveBtn.className = "btn-ghost";
      resolveBtn.onclick = async () => {
        await api(`/api/documents/duplicate-flags/${f.id}/resolve`, { method: "POST" });
        loadDuplicateFlags();
      };
      li.appendChild(info);
      li.appendChild(resolveBtn);
      list.appendChild(li);
    });
  }

  document.getElementById("scan-duplicates-btn").addEventListener("click", async function () {
    const btn = document.getElementById("scan-duplicates-btn");
    const statusEl = document.getElementById("scan-duplicates-status");
    btn.disabled = true;
    statusEl.hidden = false;
    statusEl.textContent = "Scanning…";

    const res = await api("/api/documents/scan-duplicates", { method: "POST" });
    const newFlags = await res.json();
    statusEl.textContent = newFlags.length ? `Found ${newFlags.length} new potential duplicate(s).` : "No new duplicates found.";

    btn.disabled = false;
    loadDuplicateFlags();
  });

  document.getElementById("upload-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const fileInput = document.getElementById("upload-file");
    const categoryId = document.getElementById("upload-category").value;
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    const url = TENANT_BASE + "/api/documents/upload" + (categoryId ? `?category_id=${categoryId}` : "");
    const res = await fetch(url, { method: "POST", body: formData });
    if (res.status === 401) return showLogin();

    fileInput.value = "";
    loadDocuments();
  });

  // --- Agent/Bot Configuration (Phase 8 — 3.4, extended Phase 9 — 1.6) ---
  const agentNameInput = document.getElementById("agent-name-input");
  const agentToneInput = document.getElementById("agent-tone-input");
  const agentThresholdInput = document.getElementById("confidence-threshold-input");
  const agentThresholdValue = document.getElementById("confidence-threshold-value");
  const agentSaveBtn = document.getElementById("agent-config-save");
  const agentStatus = document.getElementById("agent-config-status");

  async function loadAgentConfig() {
    const res = await api("/api/tenant/agent-config");
    if (!res.ok) {
      // admin+ only — same graceful degradation as the audit log panel.
      agentNameInput.disabled = true;
      agentToneInput.disabled = true;
      agentThresholdInput.disabled = true;
      agentSaveBtn.disabled = true;
      agentStatus.textContent = "Admin access required.";
      return;
    }
    agentNameInput.disabled = false;
    agentToneInput.disabled = false;
    agentThresholdInput.disabled = false;
    agentSaveBtn.disabled = false;
    agentStatus.textContent = "";

    const config = await res.json();
    agentNameInput.value = config.agent_name || "";
    agentToneInput.value = config.tone || "";
    // null means "no override yet" — app default (0.75) shown as the
    // starting slider position, same contract as tone's empty string.
    const initialThreshold = config.retrieval_confidence_threshold ?? 0.75;
    agentThresholdInput.value = initialThreshold;
    agentThresholdValue.textContent = Number(initialThreshold).toFixed(2);
  }

  agentThresholdInput.addEventListener("input", () => {
    agentThresholdValue.textContent = Number(agentThresholdInput.value).toFixed(2);
  });

  agentSaveBtn.addEventListener("click", async () => {
    agentStatus.textContent = "Saving…";
    const saveRes = await api("/api/tenant/agent-config", {
      method: "POST",
      body: JSON.stringify({
        agent_name: agentNameInput.value.trim() || null,
        tone: agentToneInput.value.trim() || null,
        retrieval_confidence_threshold: Number(agentThresholdInput.value),
      }),
    });
    if (!saveRes.ok) {
      let detail = "Could not save.";
      try {
        const body = await saveRes.json();
        if (body && body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch (_) { /* body wasn't JSON — keep the generic message */ }
      agentStatus.textContent = `${detail} (HTTP ${saveRes.status})`;
      return;
    }
    agentStatus.textContent = "Saved.";
  });

  // --- Audit Log (Phase 8 — 1.4) ---
  async function loadAuditLog() {
    const list = document.getElementById("audit-log-list");
    const empty = document.getElementById("audit-log-empty");
    const res = await api("/api/tenant/audit-log?days=30");
    if (!res.ok) {
      // admin+ only — editor/viewer roles see the panel but with a
      // quiet "not visible at your role" message rather than a
      // broken/erroring list (this is the first page-load-triggered
      // admin+-only panel; every other auto-loaded panel so far is
      // viewer+/editor+, so this is a new case worth handling
      // explicitly rather than letting entries.forEach throw on an
      // error body that isn't actually an array).
      empty.hidden = false;
      empty.querySelector(".empty-title").textContent = "Admin access required";
      empty.querySelector(".empty-body").textContent = "Only tenant admins can view the audit log.";
      return;
    }
    const entries = await res.json();

    list.innerHTML = "";
    empty.hidden = entries.length > 0;
    entries.forEach((e) => {
      const li = document.createElement("li");
      const who = e.admin_email || "(deleted admin)";
      const detail = e.detail ? ` — ${e.detail}` : "";
      li.innerHTML = `<span>${e.created_at} · ${who} · ${e.action} ${e.entity_type}${detail}</span>`;
      list.appendChild(li);
    });
  }

  // --- Analytics (Phase 7 — 1.3) ---
  // Hand-rolled SVG bar charts — no external charting library. This is
  // a self-hosted app; a bar chart is a rect per data point, not worth
  // a new client-side dependency for.
  function svgBarChart(values, opts) {
    const width = opts.width || 560;
    const height = opts.height || 140;
    const barGap = 4;
    const max = Math.max(1, ...values.map((v) => v.value));
    const barWidth = values.length ? (width - barGap * (values.length - 1)) / values.length : width;

    const bars = values
      .map((v, i) => {
        const barHeight = Math.round((v.value / max) * (height - 20));
        const x = i * (barWidth + barGap);
        const y = height - barHeight - 16;
        return (
          `<rect x="${x}" y="${y}" width="${Math.max(1, barWidth)}" height="${barHeight}" fill="var(--accent, #4f46e5)" rx="2">` +
          `<title>${v.label}: ${v.value}</title></rect>` +
          `<text x="${x + barWidth / 2}" y="${height - 4}" font-size="9" text-anchor="middle" fill="var(--muted, #888)">${v.shortLabel || ""}</text>`
        );
      })
      .join("");

    return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}">${bars}</svg>`;
  }

  function renderStatCard(label, value) {
    return `<div class="stat-card"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`;
  }

  async function loadAnalytics() {
    const days = document.getElementById("analytics-range").value;

    const [dashRes, flaggedRes] = await Promise.all([
      api(`/api/tenant/analytics/dashboard?days=${days}`),
      api(`/api/tenant/analytics/flagged-questions?days=${days}`),
    ]);
    const dash = await dashRes.json();
    const flagged = await flaggedRes.json();

    const csatText = dash.csat.percentage === null ? "—" : `${dash.csat.percentage}%`;
    document.getElementById("analytics-stats").innerHTML = [
      renderStatCard("Conversations", dash.conversation_count),
      renderStatCard("Answers", dash.answer_count),
      renderStatCard("Escalations", dash.escalation_count),
      renderStatCard("CSAT", csatText),
      renderStatCard("Est. cost", `$${Number(dash.cost.total_usd).toFixed(4)}`),
      renderStatCard("Flagged", dash.flagged_question_count),
    ].join("");

    const volumeValues = dash.daily_volume.map((d) => ({
      label: d.date,
      shortLabel: d.date.slice(5), // MM-DD
      value: d.count,
    }));
    document.getElementById("analytics-volume-chart").innerHTML = volumeValues.length
      ? svgBarChart(volumeValues, { height: 120 })
      : '<p class="hint">No answers in this range yet.</p>';

    const costValues = dash.cost.by_provider_model.map((c) => ({
      label: `${c.provider}/${c.model}`,
      shortLabel: c.model,
      value: Number(c.estimated_cost_usd),
    }));
    document.getElementById("analytics-cost-chart").innerHTML = costValues.length
      ? svgBarChart(costValues, { height: 100 })
      : '<p class="hint">No usage recorded in this range yet.</p>';

    const list = document.getElementById("analytics-flagged-list");
    const empty = document.getElementById("analytics-flagged-empty");
    list.innerHTML = "";
    empty.hidden = flagged.length > 0;
    flagged.forEach((f) => {
      const li = document.createElement("li");
      const snippet = f.content.length > 140 ? f.content.slice(0, 140) + "…" : f.content;
      li.innerHTML = `<span>[${f.reasons.join(", ")}] ${snippet}</span>`;
      list.appendChild(li);
    });

    document.getElementById("analytics-export-btn").href = TENANT_BASE + `/api/tenant/analytics/export.csv?days=${days}`;
  }

  document.getElementById("analytics-range").addEventListener("change", loadAnalytics);

  // --- Settings: LLM provider override ---
  async function loadLlmConfig() {
    const res = await api("/api/tenant/llm-config");
    const data = await res.json();
    const desc = document.getElementById("llm-config-desc");
    const resetBtn = document.getElementById("llm-config-reset");
    if (data) {
      desc.textContent = `Overrides the global default provider/model for this tenant. Currently using ${data.provider} / ${data.model}${data.has_custom_api_key ? " with a custom API key." : ", using the global API key."}`;
      document.getElementById("llm-provider-input").value = data.provider;
      document.getElementById("llm-model-input").value = data.model;
      resetBtn.disabled = false;
    } else {
      desc.textContent = "Overrides the global default provider/model for this tenant. No override configured — using the global default.";
      resetBtn.disabled = true;
    }
  }

  document.getElementById("llm-config-save").addEventListener("click", async function () {
    const statusEl = document.getElementById("llm-config-status");
    const model = document.getElementById("llm-model-input").value.trim();
    if (!model) {
      statusEl.textContent = "Model is required.";
      return;
    }
    const apiKeyInput = document.getElementById("llm-api-key-input");
    await api("/api/tenant/llm-config", {
      method: "POST",
      body: JSON.stringify({
        provider: document.getElementById("llm-provider-input").value,
        model,
        api_key: apiKeyInput.value || null,
      }),
    });
    apiKeyInput.value = "";
    statusEl.textContent = "Saved.";
    await loadLlmConfig();
  });

  document.getElementById("llm-config-reset").addEventListener("click", async function () {
    await api("/api/tenant/llm-config/reset", { method: "POST" });
    document.getElementById("llm-config-status").textContent = "Reverted to the global default.";
    document.getElementById("llm-model-input").value = "";
    await loadLlmConfig();
  });

  // --- Settings: support inbox ---
  async function loadSupportConfig() {
    const res = await api("/api/tenant/support-config");
    const data = await res.json();
    if (data) document.getElementById("support-email-input").value = data.support_email;
  }

  document.getElementById("support-config-save").addEventListener("click", async function () {
    const email = document.getElementById("support-email-input").value.trim();
    await api("/api/tenant/support-config", { method: "POST", body: JSON.stringify({ support_email: email }) });
    document.getElementById("support-config-status").textContent = "Saved.";
  });

  // --- Settings: prompt versions ---
  function truncatePrompt(text) {
    return text.length > 160 ? text.slice(0, 160) + "…" : text;
  }

  async function loadPromptVersions() {
    const res = await api("/api/tenant/prompt-versions");
    const versions = await res.json();
    const tbody = document.querySelector("#prompt-version-table tbody");
    const empty = document.getElementById("prompt-version-empty");
    tbody.innerHTML = "";
    empty.hidden = versions.length > 0;

    versions.forEach((v) => {
      const tr = document.createElement("tr");
      const activeBadge = v.is_active ? ' <span class="badge badge-published">active</span>' : "";
      const activateBtn = v.is_active ? "" : `<button type="button" class="btn-ghost btn-sm" data-activate-id="${v.id}">Activate</button>`;
      tr.innerHTML = `<td class="num">v${v.version_number}${activeBadge}</td><td style="max-width:360px;">${truncatePrompt(v.prompt_text)}</td><td class="num">${v.created_at || "—"}</td><td>${activateBtn}</td>`;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll("button[data-activate-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/tenant/prompt-versions/${btn.dataset.activateId}/activate`, { method: "POST" });
        loadPromptVersions();
      });
    });
  }

  document.getElementById("prompt-version-save").addEventListener("click", async function () {
    const draft = document.getElementById("prompt-draft-input");
    const text = draft.value.trim();
    if (!text) return;
    await api("/api/tenant/prompt-versions", { method: "POST", body: JSON.stringify({ prompt_text: text }) });
    draft.value = "";
    await loadPromptVersions();
  });

  // --- Settings: API keys ---
  async function loadApiKeys() {
    const res = await api("/api/api-keys");
    const keys = await res.json();
    const tbody = document.querySelector("#api-key-table tbody");
    const empty = document.getElementById("api-key-empty");
    tbody.innerHTML = "";
    empty.hidden = keys.length > 0;

    keys.forEach((k) => {
      const tr = document.createElement("tr");
      const statusBadge = k.revoked_at ? '<span class="badge badge-error">revoked</span>' : '<span class="badge badge-published">active</span>';
      const revokeBtn = k.revoked_at ? "" : `<button type="button" class="btn-danger btn-sm" data-revoke-id="${k.id}">Revoke</button>`;
      tr.innerHTML = `<td>${k.name}</td><td><span class="badge badge-draft">${k.role}</span></td><td class="num">${k.key_prefix}…</td><td class="num">${k.created_at}</td><td>${statusBadge}</td><td>${revokeBtn}</td>`;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll("button[data-revoke-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/api-keys/${btn.dataset.revokeId}/revoke`, { method: "POST" });
        loadApiKeys();
      });
    });
  }

  document.getElementById("api-key-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const nameInput = document.getElementById("api-key-name-input");
    const roleInput = document.getElementById("api-key-role-input");
    const res = await api("/api/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: nameInput.value.trim(), role: roleInput.value }),
    });
    const data = await res.json();
    document.getElementById("api-key-created-value").textContent = data.api_key;
    document.getElementById("api-key-created-banner").hidden = false;
    nameInput.value = "";
    roleInput.value = "viewer";
    await loadApiKeys();
  });

  // --- Topbar search: live-filters table rows / list items on whichever
  // admin page is currently active. Client-side only — no new endpoints,
  // matches the rest of this file's "no framework, no build step" scope. ---
  const searchInput = document.getElementById("admin-search");
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      const q = searchInput.value.trim().toLowerCase();
      const activePage = document.querySelector(".admin-page:not([hidden])");
      if (!activePage) return;
      const rows = activePage.querySelectorAll("table.data-table tbody tr, ul.plain-list > li");
      rows.forEach((row) => {
        row.style.display = !q || row.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }

  // Clear the search box whenever the active section changes so a filter
  // from one page doesn't silently linger, hiding rows, on another.
  document.querySelectorAll(".admin-nav-item[data-target]").forEach((btn) => {
    btn.addEventListener("click", function () {
      if (searchInput) {
        searchInput.value = "";
        document.querySelectorAll(".admin-page:not([hidden]) table.data-table tbody tr, .admin-page:not([hidden]) ul.plain-list > li").forEach((row) => { row.style.display = ""; });
      }
    });
  });

  // Check session on load by attempting to fetch documents.
  api("/api/documents").then(showDashboard).catch(showLogin);
})();
