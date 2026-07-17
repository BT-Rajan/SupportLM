// Admin dashboard — no framework, no build step.
(function () {
  const loginView = document.getElementById("login-view");
  const dashboardView = document.getElementById("dashboard-view");

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
    loginView.hidden = false;
    dashboardView.hidden = true;
  }

  function showDashboard() {
    loginView.hidden = true;
    dashboardView.hidden = false;
    loadCategories();
    loadSyncSources();
    loadDuplicateFlags();
    loadDocuments();
    loadAnalytics();
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

  // Check session on load by attempting to fetch documents.
  api("/api/documents").then(showDashboard).catch(showLogin);
})();
