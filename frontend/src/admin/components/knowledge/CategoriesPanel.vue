<template>
  <section class="panel">
    <h2 class="panel-title">Categories</h2>
    <form class="inline-form" @submit.prevent="submit">
      <input v-model="name" class="field-input" type="text" placeholder="New category name" required>
      <button type="submit" class="btn-primary" :disabled="submitting">Add</button>
    </form>

    <ul v-if="categories.length" class="plain-list">
      <li v-for="c in categories" :key="c.id">
        <span>{{ c.name }}</span>
        <button type="button" class="btn-danger btn-sm" @click="remove(c.id)">Delete</button>
      </li>
    </ul>
    <p v-else class="empty-state">
      <span class="empty-title">No categories yet</span>
      <span class="empty-body">Add one above to start organizing documents.</span>
    </p>
  </section>
</template>

<script setup>
import { ref } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({
  categories: { type: Array, required: true },
  api: { type: Function, required: true },
});
const emit = defineEmits(["changed"]);
const toast = useToast();

const name = ref("");
const submitting = ref(false);

async function submit() {
  submitting.value = true;
  try {
    await props.api("/api/categories", { method: "POST", body: JSON.stringify({ name: name.value.trim() }) });
    name.value = "";
    emit("changed");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not add the category.");
  } finally {
    submitting.value = false;
  }
}

async function remove(id) {
  try {
    await props.api(`/api/categories/${id}`, { method: "DELETE" });
    emit("changed");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not delete the category.");
  }
}
</script>
