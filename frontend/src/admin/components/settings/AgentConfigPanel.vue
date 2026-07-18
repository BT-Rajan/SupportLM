<template>
  <section class="panel">
    <h2 class="panel-title">Agent configuration</h2>
    <p class="panel-desc">Name and tone/personality merged into every reply's system prompt.</p>

    <p v-if="loadError" class="hint" style="color:var(--error, #c0392b); margin-bottom:14px;">{{ loadError }}</p>

    <div class="field-group">
      <label class="field-label">Agent name</label>
      <input v-model="agentName" class="field-input" type="text" placeholder="Agent name (e.g. Ava)" :disabled="disabled">
    </div>

    <div class="field-group">
      <label class="field-label">Tone / personality</label>
      <textarea
        v-model="tone"
        class="field-input"
        rows="3"
        style="width:100%; resize:vertical;"
        placeholder="Tone/personality (e.g. warm and concise, avoids jargon, upbeat)"
        :disabled="disabled"
      ></textarea>
    </div>

    <div class="field-group">
      <label class="field-label" style="margin-bottom:8px;">
        Retrieval confidence threshold: <strong style="color:var(--ink); font-family:var(--font-mono);">{{ Number(threshold).toFixed(2) }}</strong>
      </label>
      <input
        v-model.number="threshold"
        type="range"
        min="0"
        max="1"
        step="0.01"
        style="width:100%; margin-bottom:6px;"
        :disabled="disabled"
      />
      <p class="hint">
        How closely a question must match the knowledge base before the assistant will answer
        from it. Lower = answers more often, higher risk of using a weak match. Higher =
        escalates/declines more often, safer but more "I don't know" replies.
      </p>
    </div>

    <button type="button" class="btn-primary" :disabled="disabled || saving" @click="save">Save</button>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ApiError } from "../../composables/useAdminApi.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({ api: { type: Function, required: true } });
const toast = useToast();

// null means "no override yet" — 0.75 is the app default shown as the
// starting slider position, same contract as the legacy admin console.
const DEFAULT_THRESHOLD = 0.75;

const agentName = ref("");
const tone = ref("");
const threshold = ref(DEFAULT_THRESHOLD);
const saving = ref(false);
// Distinct from a normal toast-only failure: this disables the whole
// panel (e.g. a viewer/editor session hitting the admin-only endpoint)
// rather than just flashing a message, since there's nothing useful
// to save until that's resolved.
const loadError = ref("");
const disabled = computed(() => !!loadError.value);

async function load() {
  try {
    const config = await props.api("/api/tenant/agent-config");
    agentName.value = config.agent_name || "";
    tone.value = config.tone || "";
    threshold.value = config.retrieval_confidence_threshold ?? DEFAULT_THRESHOLD;
    loadError.value = "";
  } catch (err) {
    loadError.value = err instanceof ApiError ? `${err.message} (HTTP ${err.status})` : "Could not load agent configuration.";
  }
}

async function save() {
  saving.value = true;
  try {
    await props.api("/api/tenant/agent-config", {
      method: "POST",
      body: JSON.stringify({
        agent_name: agentName.value.trim() || null,
        tone: tone.value.trim() || null,
        retrieval_confidence_threshold: Number(threshold.value),
      }),
    });
    toast.success("Agent configuration saved.");
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not save agent configuration.");
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
