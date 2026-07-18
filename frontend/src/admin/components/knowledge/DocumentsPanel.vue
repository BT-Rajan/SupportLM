<template>
  <section class="panel">
    <h2 class="panel-title">Documents</h2>

    <table v-if="documents.length" class="data-table">
      <thead>
        <tr><th>Title</th><th>Status</th><th>Review state</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="d in documents" :key="d.id">
          <td>{{ d.title }}</td>
          <td>
            <span v-if="d.status === 'error'" class="badge badge-error" :title="d.error_message || ''">error</span>
            <span v-else class="badge badge-draft">{{ d.status }}</span>
          </td>
          <td>
            <select class="field-input" :value="d.review_state" @change="setReviewState(d, $event.target.value)">
              <option v-for="s in reviewStates" :key="s" :value="s">{{ s }}</option>
            </select>
          </td>
          <td>
            <div style="display:flex; gap:8px; justify-content:flex-end;">
              <button v-if="d.status !== 'ready'" type="button" class="btn-ghost btn-sm" @click="retry(d)">Retry</button>
              <button type="button" class="btn-danger btn-sm" @click="remove(d)">Delete</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty-state">
      <span class="empty-title">No documents yet</span>
      <span class="empty-body">Upload a Markdown file above to build your knowledge base.</span>
    </p>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ api: { type: Function, required: true } });
const toast = useToast();

const documents = ref([]);
const reviewStates = ["draft", "review", "published"];

async function load() {
  try {
    documents.value = await props.api("/api/documents");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load documents.");
  }
}

async function setReviewState(doc, state) {
  const prev = doc.review_state;
  doc.review_state = state; // optimistic — matches prior behavior of trusting the picked value
  try {
    await props.api(`/api/documents/${doc.id}/review-state`, { method: "POST", body: JSON.stringify({ state }) });
  } catch (err) {
    doc.review_state = prev;
    toast.error(err instanceof ApiError ? err.message : "Could not update the review state.");
  }
}

async function retry(doc) {
  try {
    const updated = await props.api(`/api/documents/${doc.id}/reindex`, { method: "POST" });
    Object.assign(doc, updated);
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not retry processing.");
  }
}

async function remove(doc) {
  try {
    await props.api(`/api/documents/${doc.id}`, { method: "DELETE" });
    await load();
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not delete the document.");
  }
}

onMounted(load);
defineExpose({ load });
</script>
