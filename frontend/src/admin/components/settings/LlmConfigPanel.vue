<template>
  <section class="panel">
    <h2 class="panel-title">LLM provider</h2>
    <p class="panel-desc">
      Overrides the global default provider/model for this tenant.
      <span v-if="current"> Currently using <strong>{{ current.provider }}</strong> / <strong>{{ current.model }}</strong>{{ current.has_custom_api_key ? " with a custom API key." : ", using the global API key." }}</span>
      <span v-else> No override configured — using the global default.</span>
    </p>

    <div class="field-group">
      <label class="field-label">Provider</label>
      <select v-model="provider" class="field-input">
        <option value="deepseek">DeepSeek</option>
        <option value="openai">OpenAI</option>
        <option value="anthropic">Anthropic</option>
      </select>
    </div>
    <div class="field-group">
      <label class="field-label">Model</label>
      <input v-model="model" class="field-input" type="text" placeholder="e.g. deepseek-chat">
    </div>
    <div class="field-group">
      <label class="field-label">Custom API key (optional — leave blank to use the global key)</label>
      <input v-model="apiKey" class="field-input" type="password" placeholder="sk-…" autocomplete="off">
    </div>

    <div style="display:flex; gap:10px;">
      <button type="button" class="btn-primary" :disabled="saving" @click="save">Save</button>
      <button type="button" class="btn-ghost" :disabled="saving || !current" @click="reset">Reset to global default</button>
    </div>
  </section>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ api: { type: Function, required: true } });
const toast = useToast();

const current = ref(null);
const provider = ref("deepseek");
const model = ref("");
const apiKey = ref("");
const saving = ref(false);

async function load() {
  try {
    const data = await props.api("/api/tenant/llm-config");
    current.value = data;
    if (data) {
      provider.value = data.provider;
      model.value = data.model;
    }
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load LLM configuration.");
  }
}

async function save() {
  if (!model.value.trim()) {
    toast.error("Model is required.");
    return;
  }
  saving.value = true;
  try {
    const data = await props.api("/api/tenant/llm-config", {
      method: "POST",
      body: JSON.stringify({ provider: provider.value, model: model.value.trim(), api_key: apiKey.value || null }),
    });
    current.value = data;
    apiKey.value = "";
    toast.success("LLM configuration saved.");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not save LLM configuration.");
  } finally {
    saving.value = false;
  }
}

async function reset() {
  saving.value = true;
  try {
    await props.api("/api/tenant/llm-config/reset", { method: "POST" });
    current.value = null;
    toast.success("Reverted to the global default.");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not reset LLM configuration.");
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
