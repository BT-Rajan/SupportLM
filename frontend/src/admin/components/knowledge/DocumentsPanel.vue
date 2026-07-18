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
            <span class="badge" :class="reviewBadgeClass(d.review_state)">{{ d.review_state }}</span>
          </td>
          <td>
            <div style="display:flex; gap:8px; justify-content:flex-end; flex-wrap:wrap;">
              <button
                v-for="t in transitions(d.review_state)"
                :key="t.state"
                type="button"
                class="btn-ghost btn-sm"
                :disabled="movingId === d.id"
                @click="setReviewState(d, t.state)"
              >{{ t.label }}</button>
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
// Deliberately no direct draft <-> published jump: only the adjacent
// step forward, plus one step back to undo a mistake. A document only
// counts toward chat retrieval once it's "published" (see
// app/services/vector_store.py), so skipping straight there from
// "draft" is exactly the "changed for no reason" complaint this
// replaces — a stray click on a free-choice dropdown could silently
// make unreviewed content live.
const TRANSITIONS = {
  draft: [{ state: "review", label: "Submit for review →" }],
  review: [
    { state: "draft", label: "← Back to draft" },
    { state: "published", label: "Publish →" },
  ],
  published: [{ state: "review", label: "← Unpublish (send back to review)" }],
};
const movingId = ref(null);

function transitions(state) {
  return TRANSITIONS[state] || [];
}

function reviewBadgeClass(state) {
  return state === "published" ? "badge-published" : state === "review" ? "badge-review" : "badge-draft";
}

async function load() {
  try {
    documents.value = await props.api("/api/documents");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load documents.");
  }
}

async function setReviewState(doc, state) {
  const prev = doc.review_state;
  movingId.value = doc.id;
  doc.review_state = state; // optimistic — matches prior behavior of trusting the picked value
  try {
    await props.api(`/api/documents/${doc.id}/review-state`, { method: "POST", body: JSON.stringify({ state }) });
  } catch (err) {
    doc.review_state = prev;
    toast.error(err instanceof ApiError ? err.message : "Could not update the review state.");
  } finally {
    movingId.value = null;
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
