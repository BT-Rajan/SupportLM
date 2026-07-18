<template>
  <section class="panel">
    <h2 class="panel-title">Upload document</h2>
    <form class="inline-form" @submit.prevent="submit">
      <input ref="fileInput" class="field-input" type="file" accept=".md,.markdown" required>
      <select v-model="categoryId" class="field-input">
        <option :value="null">No category</option>
        <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
      <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? "Uploading…" : "Upload" }}</button>
    </form>
    <p class="hint">New uploads start as drafts — publish them below once they're ready to answer questions.</p>
  </section>
</template>

<script setup>
import { ref } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({
  categories: { type: Array, required: true },
  api: { type: Function, required: true },
  base: { type: String, required: true },
});
const emit = defineEmits(["changed"]);
const toast = useToast();

const fileInput = ref(null);
const categoryId = ref(null);
const submitting = ref(false);

async function submit() {
  const file = fileInput.value.files[0];
  if (!file) return;
  submitting.value = true;
  try {
    const formData = new FormData();
    formData.append("file", file);
    const url = props.base + "/api/documents/upload" + (categoryId.value ? `?category_id=${categoryId.value}` : "");
    const res = await fetch(url, { method: "POST", body: formData });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body && body.detail);
    }
    fileInput.value.value = "";
    categoryId.value = null;
    toast.success("Document uploaded — processing in the background.");
    emit("changed");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not upload the document.");
  } finally {
    submitting.value = false;
  }
}
</script>
