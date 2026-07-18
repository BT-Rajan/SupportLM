// Admin section navigation — sidebar tabs + page transitions.
// Deliberately separate from admin.js: this file only ever touches
// visibility/active-state, never tenant data, so the two can be read
// (and changed) independently. Follows the same no-framework,
// hidden-attribute-toggle idiom admin.js already uses for the
// login/dashboard swap, so the page-load transition on that swap
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
      if (btn.classList.contains("active")) return;
      activate(btn.dataset.target);
    });
  });

  activate(navItems[0].dataset.target);
})();
