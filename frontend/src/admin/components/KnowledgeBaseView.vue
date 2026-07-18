<template>
  <CategoriesPanel :categories="categories" :api="api" @changed="loadCategories" />
  <UploadPanel :categories="categories" :api="api" :base="base" @changed="onDocsChanged" />
  <SyncSourcesPanel :api="api" @changed="onDocsChanged" />
  <DuplicatesPanel :api="api" />
  <DocumentsPanel ref="documentsPanel" :api="api" />
</template>

<script setup>
import { ref, onMounted } from "vue";
import CategoriesPanel from "./knowledge/CategoriesPanel.vue";
import UploadPanel from "./knowledge/UploadPanel.vue";
import SyncSourcesPanel from "./knowledge/SyncSourcesPanel.vue";
import DuplicatesPanel from "./knowledge/DuplicatesPanel.vue";
import DocumentsPanel from "./knowledge/DocumentsPanel.vue";
import { useAdminApi, ApiError } from "../composables/useAdminApi.js";
import { useToast } from "../composables/useToast.js";

const props = defineProps({ tenantSlug: { type: String, required: true } });
const { api, base } = useAdminApi(props.tenantSlug);
const toast = useToast();

const categories = ref([]);
const documentsPanel = ref(null);

async function loadCategories() {
  try {
    categories.value = await api("/api/categories");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load categories.");
  }
}

function onDocsChanged() {
  documentsPanel.value && documentsPanel.value.load();
}

onMounted(loadCategories);
</script>
