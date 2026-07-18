<template>
  <section class="panel">
    <h2 class="panel-title">API keys</h2>
    <p class="panel-desc">Programmatic credentials for calling the admin API directly. A newly created key's secret is shown once — copy it now.</p>

    <div v-if="justCreated" style="background:var(--accent-soft); border:1px solid var(--accent); border-radius:var(--radius-sm); padding:12px 14px; margin-bottom:16px;">
      <p style="margin:0 0 6px; font-size:12.5px; color:var(--accent-ink); font-weight:600;">Copy this key now — it won't be shown again.</p>
      <code style="display:block; font-family:var(--font-mono); font-size:12.5px; word-break:break-all; background:var(--surface); padding:8px 10px; border-radius:6px;">{{ justCreated }}</code>
    </div>

    <form class="inline-form" @submit.prevent="create">
      <input v-model="name" class="field-input" type="text" placeholder="Key name (e.g. Zapier integration)" required>
      <select v-model="role" class="field-input">
        <option value="viewer">Viewer</option>
        <option value="editor">Editor</option>
        <option value="admin">Admin</option>
        <option value="owner">Owner</option>
      </select>
      <button type="submit" class="btn-primary" :disabled="saving">Create key</button>
    </form>

    <table v-if="keys.length" class="data-table">
      <thead>
        <tr><th>Name</th><th>Role</th><th>Prefix</th><th>Created</th><th>Status</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="k in keys" :key="k.id">
          <td>{{ k.name }}</td>
          <td><span class="badge badge-draft">{{ k.role }}</span></td>
          <td class="num">{{ k.key_prefix }}…</td>
          <td class="num">{{ k.created_at }}</td>
          <td>
            <span v-if="k.revoked_at" class="badge badge-error">revoked</span>
            <span v-else class="badge badge-published">active</span>
          </td>
          <td><button v-if="!k.revoked_at" type="button" class="btn-danger btn-sm" @click="revoke(k)">Revoke</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty-state">
      <span class="empty-title">No API keys yet</span>
      <span class="empty-body">Create one above to call the admin API programmatically.</span>
    </p>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ api: { type: Function, required: true } });
const toast = useToast();

const keys = ref([]);
const name = ref("");
const role = ref("viewer");
const saving = ref(false);
const justCreated = ref("");

async function load() {
  try {
    keys.value = await props.api("/api/api-keys");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load API keys.");
  }
}

async function create() {
  saving.value = true;
  try {
    const data = await props.api("/api/api-keys", { method: "POST", body: JSON.stringify({ name: name.value.trim(), role: role.value }) });
    justCreated.value = data.api_key;
    name.value = "";
    role.value = "viewer";
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not create the API key.");
  } finally {
    saving.value = false;
  }
}

async function revoke(k) {
  try {
    await props.api(`/api/api-keys/${k.id}/revoke`, { method: "POST" });
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not revoke the key.");
  }
}

onMounted(load);
</script>
