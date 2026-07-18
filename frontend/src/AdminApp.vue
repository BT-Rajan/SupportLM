<template>
  <p v-if="authState === 'loading'" class="hint" style="text-align:center;padding:60px 0;">Checking session…</p>

  <LoginView
    v-else-if="authState === 'login'"
    :tenant-slug="tenantSlug"
    @logged-in="checkSession"
  />

  <div v-else class="admin-shell">
    <aside class="admin-sidebar">
      <div class="admin-brand">
        <BrandAura monogram="S" size="md" />
        <div class="admin-brand-text">
          <span class="admin-brand-name">Admin</span>
          <span class="admin-brand-slug">{{ tenantSlug }}</span>
        </div>
      </div>
      <nav class="admin-nav">
        <button
          v-for="s in sections"
          :key="s.id"
          type="button"
          class="admin-nav-item"
          :class="{ active: section === s.id }"
          @click="section = s.id"
        >{{ s.label }}</button>
      </nav>
      <div class="admin-sidebar-foot">
        <button type="button" class="btn-ghost" style="width:100%;" @click="logout">Log out</button>
      </div>
    </aside>

    <div class="admin-main">
      <header class="admin-topbar">
        <div>
          <h1 class="admin-page-title">{{ activeSection.label }}</h1>
          <p class="admin-page-sub">{{ activeSection.sub }}</p>
        </div>
      </header>
      <div class="admin-content">
        <OverviewView v-if="section === 'overview'" :tenant-slug="tenantSlug" />
        <KnowledgeBaseView v-else-if="section === 'knowledge'" :tenant-slug="tenantSlug" />
        <AuditLogView v-else-if="section === 'audit'" :tenant-slug="tenantSlug" />
        <SettingsView v-else-if="section === 'settings'" :tenant-slug="tenantSlug" />
      </div>
    </div>
  </div>

  <ToastHost />
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import BrandAura from "./components/BrandAura.vue";
import LoginView from "./admin/components/LoginView.vue";
import OverviewView from "./admin/components/OverviewView.vue";
import KnowledgeBaseView from "./admin/components/KnowledgeBaseView.vue";
import AuditLogView from "./admin/components/AuditLogView.vue";
import SettingsView from "./admin/components/SettingsView.vue";
import ToastHost from "./admin/components/ToastHost.vue";
import { useAdminApi } from "./admin/composables/useAdminApi.js";

const props = defineProps({
  config: { type: Object, default: () => ({}) },
});

const tenantSlug = props.config.tenant_slug;
const { api } = useAdminApi(tenantSlug);

const authState = ref("loading"); // 'loading' | 'login' | 'ready'
const section = ref("overview");

const sections = [
  { id: "overview", label: "Overview", sub: "Usage, cost, and satisfaction at a glance." },
  { id: "knowledge", label: "Knowledge base", sub: "Categories, documents, website sync, and duplicate review." },
  { id: "audit", label: "Audit log", sub: "Uploads, edits, deletes, and admin logins for the last 30 days." },
  { id: "settings", label: "Settings", sub: "LLM provider, prompt versions, support inbox, and API keys." },
];
const activeSection = computed(() => sections.find((s) => s.id === section.value) || sections[0]);

async function checkSession() {
  authState.value = "loading";
  try {
    // No dedicated "am I logged in" endpoint — a viewer-level list
    // call is the lightest existing route that requires a valid,
    // tenant-linked session, same probe the previous vanilla-JS
    // console used.
    await api("/api/documents");
    authState.value = "ready";
  } catch {
    authState.value = "login";
  }
}

async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } finally {
    authState.value = "login";
  }
}

onMounted(checkSession);
onMounted(() => {
  window.addEventListener("supportlm-admin-unauthorized", () => {
    authState.value = "login";
  });
});
</script>
