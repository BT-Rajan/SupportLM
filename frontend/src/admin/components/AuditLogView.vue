<template>
  <section class="panel">
    <p class="panel-desc">Uploads, edits, deletes, and admin logins for the last 30 days.</p>

    <table v-if="entries.length" class="data-table">
      <thead>
        <tr><th>When</th><th>Admin</th><th>Action</th><th>Entity</th><th>Detail</th><th>IP</th></tr>
      </thead>
      <tbody>
        <tr v-for="e in entries" :key="e.id">
          <td class="num">{{ e.created_at }}</td>
          <td>{{ e.admin_email || "—" }}</td>
          <td><span class="badge badge-review">{{ e.action }}</span></td>
          <td>{{ e.entity_type }} #{{ e.entity_id }}</td>
          <td>{{ e.detail || "—" }}</td>
          <td class="num">{{ e.ip_address || "—" }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty-state">
      <span class="empty-title">No recent activity</span>
      <span class="empty-body">Uploads, edits, deletes, and logins will show up here.</span>
    </p>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { useAdminApi, ApiError } from "../composables/useAdminApi.js";
import { useToast } from "../composables/useToast.js";

const props = defineProps({ tenantSlug: { type: String, required: true } });
const { api } = useAdminApi(props.tenantSlug);
const toast = useToast();

const entries = ref([]);

async function load() {
  try {
    entries.value = await api("/api/tenant/audit-log?days=30");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load the audit log.");
  }
}

onMounted(load);
</script>
