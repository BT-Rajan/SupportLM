<template>
  <section class="panel">
    <h2 class="panel-title">Website sync</h2>
    <form class="inline-form" @submit.prevent="submit">
      <input v-model="url" class="field-input" type="url" placeholder="https://example.com/help/billing" required>
      <button type="submit" class="btn-primary" :disabled="submitting">Add URL</button>
    </form>

    <ul v-if="sources.length" class="plain-list">
      <li v-for="s in sources" :key="s.id">
        <span>{{ s.url }}<span v-if="s.last_synced_at" class="hint" style="margin:0 0 0 8px;">last synced {{ s.last_synced_at }}</span></span>
        <button type="button" class="btn-danger btn-sm" @click="remove(s.id)">Delete</button>
      </li>
    </ul>
    <p v-else class="empty-state">
      <span class="empty-title">No sync sources yet</span>
      <span class="empty-body">Add a URL above to keep a page synced into your knowledge base.</span>
    </p>

    <button type="button" class="btn-ghost" :disabled="syncing" @click="syncNow">{{ syncing ? "Syncing…" : "Sync now" }}</button>
    <p v-if="syncStatus" class="hint">{{ syncStatus }}</p>
    <p class="hint">Synced pages start as drafts too — publish them below once they're ready. Sync is manual only; nothing runs automatically.</p>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({
  api: { type: Function, required: true },
});
const emit = defineEmits(["changed"]);
const toast = useToast();

const sources = ref([]);
const url = ref("");
const submitting = ref(false);
const syncing = ref(false);
const syncStatus = ref("");

async function load() {
  try {
    sources.value = await props.api("/api/documents/sync-sources");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load sync sources.");
  }
}

async function submit() {
  submitting.value = true;
  try {
    await props.api("/api/documents/sync-sources", { method: "POST", body: JSON.stringify({ url: url.value.trim() }) });
    url.value = "";
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not add the sync source.");
  } finally {
    submitting.value = false;
  }
}

async function remove(id) {
  try {
    await props.api(`/api/documents/sync-sources/${id}`, { method: "DELETE" });
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not remove the sync source.");
  }
}

async function syncNow() {
  syncing.value = true;
  syncStatus.value = "";
  try {
    const results = await props.api("/api/documents/sync-sources/sync-now", { method: "POST" });
    syncStatus.value = `Synced ${results.length} source${results.length === 1 ? "" : "s"}.`;
    await load();
    emit("changed");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Sync failed.");
  } finally {
    syncing.value = false;
  }
}

onMounted(load);
defineExpose({ load });
</script>
