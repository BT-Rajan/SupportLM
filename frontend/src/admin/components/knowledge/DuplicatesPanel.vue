<template>
  <section class="panel">
    <h2 class="panel-title">Duplicate content review</h2>
    <button type="button" class="btn-ghost" :disabled="scanning" @click="scan">{{ scanning ? "Scanning…" : "Scan for duplicates" }}</button>
    <p v-if="scanStatus" class="hint">{{ scanStatus }}</p>

    <ul v-if="flags.length" class="plain-list" style="margin-top:14px;">
      <li v-for="f in flags" :key="f.id" style="display:block;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
          <span>
            <strong>{{ f.title_a }}</strong> ({{ f.label_a }}) &harr; <strong>{{ f.title_b }}</strong> ({{ f.label_b }})
            <span class="hint" style="margin:0 0 0 6px;">{{ Math.round(f.similarity * 100) }}% similar · {{ f.source }}</span>
          </span>
          <button type="button" class="btn-ghost btn-sm" @click="resolve(f.id)">Dismiss</button>
        </div>
      </li>
    </ul>
    <p v-else class="empty-state">
      <span class="empty-title">No duplicates flagged</span>
      <span class="empty-body">Run a scan above to check for near-duplicate titles and headings.</span>
    </p>
    <p class="hint">Compares document titles and section headings for near-duplicate text. Scanning is manual only.</p>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ api: { type: Function, required: true } });
const toast = useToast();

const flags = ref([]);
const scanning = ref(false);
const scanStatus = ref("");

async function load() {
  try {
    flags.value = await props.api("/api/documents/duplicate-flags");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load duplicate flags.");
  }
}

async function scan() {
  scanning.value = true;
  scanStatus.value = "";
  try {
    const newFlags = await props.api("/api/documents/scan-duplicates", { method: "POST" });
    scanStatus.value = newFlags.length ? `Found ${newFlags.length} new duplicate pair(s).` : "No new duplicates found.";
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Scan failed.");
  } finally {
    scanning.value = false;
  }
}

async function resolve(id) {
  try {
    await props.api(`/api/documents/duplicate-flags/${id}/resolve`, { method: "POST" });
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not dismiss the flag.");
  }
}

onMounted(load);
</script>
