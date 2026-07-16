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
    loadDocuments();
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

  // Check session on load by attempting to fetch documents.
  api("/api/documents").then(showDashboard).catch(showLogin);
})();
