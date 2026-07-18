// Admin section navigation — sidebar tabs, page transitions, and the
// collapsible/overlay drawer. Deliberately separate from admin.js: this
// file only ever touches visibility/active-state, never tenant data, so
// the two can be read (and changed) independently. Follows the same
// no-framework, hidden-attribute-toggle idiom admin.js already uses for
// the login/dashboard swap, so the page-load transition on that swap
// (see admin.css's .auth-shell / .admin-shell animations) and this
// section-switch transition both restart the same way: toggling the
// `hidden` attribute takes the element out of and back into the
// render tree, which is what re-triggers a CSS animation.
(function () {
  const navItems = Array.prototype.slice.call(document.querySelectorAll(".admin-nav-item[data-target]"));
  const pages = Array.prototype.slice.call(document.querySelectorAll(".admin-page[data-page]"));
  const titleEl = document.getElementById("admin-page-title");
  const subEl = document.getElementById("admin-page-sub");

  if (!navItems.length || !pages.length) return;

  function activate(target) {
    pages.forEach(function (page) {
      page.hidden = page.dataset.page !== target;
    });
    navItems.forEach(function (btn) {
      const isActive = btn.dataset.target === target;
      btn.classList.toggle("active", isActive);
      if (isActive) {
        if (titleEl) titleEl.textContent = btn.dataset.label || btn.textContent.trim();
        if (subEl) subEl.textContent = btn.dataset.sub || "";
      }
    });
    // Scroll the newly active page into view from the top — switching
    // sections should feel like arriving on a fresh page, not landing
    // mid-scroll on wherever the previous section left off.
    const content = document.querySelector(".admin-content");
    if (content) content.scrollTop = 0;
  }

  navItems.forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!btn.classList.contains("active")) activate(btn.dataset.target);
      closeMobileDrawer();
    });
  });

  activate(navItems[0].dataset.target);

  // ---- Drawer: desktop collapse (280px <-> 72px, persisted) + mobile
  // overlay (fixed, off-canvas, backdrop-dismissible) --------------------
  const sidebar = document.getElementById("admin-sidebar");
  const collapseToggle = document.getElementById("sidebar-collapse-toggle");
  const openToggle = document.getElementById("sidebar-open-toggle");
  const backdrop = document.getElementById("sidebar-backdrop");
  const COLLAPSE_KEY = "supportlm-admin-sidebar-collapsed";

  if (sidebar && collapseToggle) {
    if (window.localStorage && window.localStorage.getItem(COLLAPSE_KEY) === "1") {
      sidebar.classList.add("collapsed");
      collapseToggle.setAttribute("aria-label", "Expand sidebar");
    }
    collapseToggle.addEventListener("click", function () {
      const collapsed = sidebar.classList.toggle("collapsed");
      collapseToggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
      collapseToggle.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
      if (window.localStorage) window.localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    });
  }

  function openMobileDrawer() {
    if (!sidebar) return;
    sidebar.classList.add("mobile-open");
    if (backdrop) backdrop.hidden = false;
    requestAnimationFrame(function () { if (backdrop) backdrop.classList.add("visible"); });
    if (openToggle) openToggle.setAttribute("aria-expanded", "true");
  }
  function closeMobileDrawer() {
    if (!sidebar || !sidebar.classList.contains("mobile-open")) return;
    sidebar.classList.remove("mobile-open");
    if (backdrop) backdrop.classList.remove("visible");
    if (openToggle) openToggle.setAttribute("aria-expanded", "false");
    setTimeout(function () { if (backdrop && !sidebar.classList.contains("mobile-open")) backdrop.hidden = true; }, 200);
  }

  if (openToggle) openToggle.addEventListener("click", openMobileDrawer);
  if (backdrop) backdrop.addEventListener("click", closeMobileDrawer);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMobileDrawer();
  });
})();
