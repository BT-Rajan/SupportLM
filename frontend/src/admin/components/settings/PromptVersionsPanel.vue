<template>
  <section class="panel">
    <h2 class="panel-title">Prompt versions</h2>
    <p class="panel-desc">Draft a new system prompt, then activate it once you're happy — activating changes what every visitor's conversation sees immediately.</p>

    <div class="field-group">
      <textarea v-model="draft" class="field-input" rows="4" style="width:100%; resize:vertical;" placeholder="System prompt text…"></textarea>
    </div>
    <button type="button" class="btn-primary" :disabled="saving || !draft.trim()" @click="createVersion">Save as new version</button>

    <table v-if="versions.length" class="data-table" style="margin-top:20px;">
      <thead>
        <tr><th>Version</th><th>Prompt</th><th>Created</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="v in versions" :key="v.id">
          <td class="num">v{{ v.version_number }} <span v-if="v.is_active" class="badge badge-published" style="margin-left:6px;">active</span></td>
          <td style="max-width:360px;">{{ truncate(v.prompt_text) }}</td>
          <td class="num">{{ v.created_at || "—" }}</td>
          <td><button v-if="!v.is_active" type="button" class="btn-ghost btn-sm" @click="activate(v)">Activate</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty-state">
      <span class="empty-title">No prompt versions yet</span>
      <span class="empty-body">Save one above to get started.</span>
    </p>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ api: { type: Function, required: true } });
const toast = useToast();

const versions = ref([]);
const draft = ref("");
const saving = ref(false);

function truncate(text) {
  return text.length > 160 ? text.slice(0, 160) + "…" : text;
}

async function load() {
  try {
    versions.value = await props.api("/api/tenant/prompt-versions");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load prompt versions.");
  }
}

async function createVersion() {
  saving.value = true;
  try {
    await props.api("/api/tenant/prompt-versions", { method: "POST", body: JSON.stringify({ prompt_text: draft.value.trim() }) });
    draft.value = "";
    toast.success("Prompt version saved as a draft.");
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not save the prompt version.");
  } finally {
    saving.value = false;
  }
}

async function activate(v) {
  try {
    await props.api(`/api/tenant/prompt-versions/${v.id}/activate`, { method: "POST" });
    toast.success(`Version v${v.version_number} is now active.`);
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not activate this version.");
  }
}

onMounted(load);
</script>
