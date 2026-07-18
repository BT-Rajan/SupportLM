<template>
  <section class="panel">
    <h2 class="panel-title">Documents</h2>

    <table v-if="documents.length" class="data-table">
      <thead>
        <tr><th>Title</th><th>Status</th><th>Review state</th><th></th></tr>
      </thead>
      <tbody>
        <template v-for="d in documents" :key="d.id">
          <tr>
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
                <button type="button" class="btn-ghost btn-sm" @click="togglePreview(d)">
                  {{ previewOpenId === d.id ? "Hide content" : "View content" }}
                </button>
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
          <tr v-if="previewOpenId === d.id">
            <td colspan="4">
              <p v-if="previewLoading" class="hint">Loading…</p>
              <template v-else-if="previewError">
                <p class="hint" style="color:var(--error, #c0392b);">{{ previewError }}</p>
              </template>
              <template v-else-if="preview">
                <p class="hint" style="margin-bottom:6px;">
                  {{ preview.chunk_count }} chunk{{ preview.chunk_count === 1 ? "" : "s" }} stored for this document.
                  This is the actual text that was chunked and embedded — if it looks like navigation/boilerplate
                  rather than the page's real content, the source likely needs JavaScript to render and a plain
                  fetch won't capture it.
                </p>
                <pre style="white-space:pre-wrap; max-height:280px; overflow:auto; background:var(--surface-alt); border:1px solid var(--border); border-radius:8px; padding:12px; font-family:var(--font-mono); font-size:12px;">{{ preview.content }}<span v-if="preview.truncated">…</span></pre>
              </template>
            </td>
          </tr>
        </template>
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

const previewOpenId = ref(null);
const preview = ref(null);
const previewLoading = ref(false);
const previewError = ref("");

function transitions(state) {
  return TRANSITIONS[state] || [];
}

function reviewBadgeClass(state) {
  return state === "published" ? "badge-published" : state === "review" ? "badge-review" : "badge-draft";
}

async function togglePreview(doc) {
  if (previewOpenId.value === doc.id) {
    previewOpenId.value = null;
    return;
  }
  previewOpenId.value = doc.id;
  preview.value = null;
  previewError.value = "";
  previewLoading.value = true;
  try {
    preview.value = await props.api(`/api/documents/${doc.id}/preview`);
  } catch (err) {
    previewError.value = err instanceof ApiError ? err.message : "Could not load document content.";
  } finally {
    previewLoading.value = false;
  }
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
