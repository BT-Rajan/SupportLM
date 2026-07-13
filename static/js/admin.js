// Minimal admin dashboard — no framework, no build step.
(function () {
  const loginView = document.getElementById("login-view");
  const dashboardView = document.getElementById("dashboard-view");

  async function api(path, options = {}) {
    const res = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    if (res.status === 401) {
      showLogin();
      throw new Error("Not authenticated");
    }
    return res;
  }

  function showLogin() {
    loginView.style.display = "block";
    dashboardView.style.display = "none";
  }

  function showDashboard() {
    loginView.style.display = "none";
    dashboardView.style.display = "block";
    loadCategories();
    loadDocuments();
  }

  // --- Login ---
  document.getElementById("login-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const email = document.getElementById("login-email").value;
    const password = document.getElementById("login-password").value;
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (res.ok) {
      showDashboard();
    } else {
      document.getElementById("login-error").textContent = "Invalid email or password.";
    }
  });

  document.getElementById("logout-btn").addEventListener("click", async function () {
    await fetch("/api/auth/logout", { method: "POST" });
    showLogin();
  });

  // --- Categories ---
  async function loadCategories() {
    const res = await api("/api/categories");
    const categories = await res.json();

    const list = document.getElementById("category-list");
    list.innerHTML = "";
    const select = document.getElementById("upload-category");
    select.innerHTML = '<option value="">No category</option>';

    categories.forEach((c) => {
      const li = document.createElement("li");
      li.innerHTML = `<span>${c.name}</span>`;
      const delBtn = document.createElement("button");
      delBtn.textContent = "Delete";
      delBtn.className = "danger";
      delBtn.onclick = async () => {
        await api(`/api/categories/${c.id}`, { method: "DELETE" });
        loadCategories();
      };
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
  async function loadDocuments() {
    const res = await api("/api/documents");
    const docs = await res.json();
    const tbody = document.querySelector("#document-table tbody");
    tbody.innerHTML = "";
    docs.forEach((d) => {
      const tr = document.createElement("tr");
      const statusCell = d.status === "error"
        ? `<span class="error" title="${(d.error_message || "").replace(/"/g, '&quot;')}">error</span>`
        : d.status;
      const retryBtn = d.status === "error" ? `<button data-retry-id="${d.id}">Retry</button>` : "";
      const delBtn = `<button class="danger" data-id="${d.id}">Delete</button>`;
      tr.innerHTML = `<td>${d.title}</td><td>${statusCell}</td><td>${retryBtn} ${delBtn}</td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll("button.danger").forEach((btn) => {
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
  }

  document.getElementById("upload-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const fileInput = document.getElementById("upload-file");
    const categoryId = document.getElementById("upload-category").value;
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    const url = "/api/documents/upload" + (categoryId ? `?category_id=${categoryId}` : "");
    const res = await fetch(url, { method: "POST", body: formData });
    if (res.status === 401) return showLogin();

    fileInput.value = "";
    loadDocuments();
  });

  // Check session on load by attempting to fetch documents.
  api("/api/documents").then(showDashboard).catch(showLogin);
})();
