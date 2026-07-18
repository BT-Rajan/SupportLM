<template>
  <section class="panel">
    <h2 class="panel-title">Support inbox</h2>
    <p class="panel-desc">Where escalated conversations get routed when a visitor asks for a human follow-up.</p>
    <div class="inline-form">
      <input v-model="email" class="field-input" type="email" placeholder="support@yourcompany.com">
      <button type="button" class="btn-primary" :disabled="saving" @click="save">Save</button>
    </div>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ api: { type: Function, required: true } });
const toast = useToast();

const email = ref("");
const saving = ref(false);

async function load() {
  try {
    const data = await props.api("/api/tenant/support-config");
    if (data) email.value = data.support_email;
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load support inbox configuration.");
  }
}

async function save() {
  saving.value = true;
  try {
    await props.api("/api/tenant/support-config", { method: "POST", body: JSON.stringify({ support_email: email.value.trim() }) });
    toast.success("Support inbox saved.");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not save the support inbox.");
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
