<template>
  <div class="transcript-panel">
    <input
      ref="emailInput"
      v-model="email"
      type="email"
      class="transcript-input"
      placeholder="you@example.com"
      aria-label="Your email address"
      autocomplete="email"
      :disabled="sending"
      @keydown.enter.prevent="submit"
    />
    <button type="button" class="transcript-send" :disabled="sending" @click="submit">Send</button>
    <button type="button" class="transcript-cancel" aria-label="Cancel" @click="$emit('close')">✕</button>
  </div>
  <p v-if="status" class="transcript-status" :class="statusKind">{{ status }}</p>
</template>

<script setup>
import { ref, onMounted } from "vue";

const props = defineProps({
  onSend: { type: Function, required: true },
});
const emit = defineEmits(["close"]);

const email = ref("");
const sending = ref(false);
const status = ref("");
const statusKind = ref("");
const emailInput = ref(null);

onMounted(() => emailInput.value && emailInput.value.focus());

async function submit() {
  const value = email.value.trim();
  if (!value) {
    status.value = "Enter an email address first.";
    statusKind.value = "error";
    return;
  }
  sending.value = true;
  status.value = "Sending…";
  statusKind.value = "";
  try {
    await props.onSend(value);
    status.value = "Sent! Check your inbox.";
    statusKind.value = "success";
    email.value = "";
    setTimeout(() => emit("close"), 1800);
  } catch (err) {
    status.value = err.message || "Could not send the transcript.";
    statusKind.value = "error";
  } finally {
    sending.value = false;
  }
}
</script>

<style scoped>
.transcript-panel {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 20px;
  border-top: 1px solid var(--border);
  background: var(--surface-alt);
}
.transcript-input {
  flex: 1;
  font-family: var(--font-body);
  font-size: 13.5px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
  background: var(--surface);
  transition: border-color 0.15s ease;
}
.transcript-input:focus { border-color: var(--accent); }
.transcript-send {
  flex-shrink: 0;
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: var(--accent);
  border: none;
  border-radius: var(--radius-sm);
  padding: 9px 15px;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.1s ease;
}
.transcript-send:hover:not(:disabled) { background: var(--accent-ink); }
.transcript-send:active:not(:disabled) { transform: scale(0.96); }
.transcript-send:disabled { background: var(--border); cursor: not-allowed; }
.transcript-cancel {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.15s ease;
}
.transcript-cancel:hover { border-color: var(--accent); }
.transcript-status {
  font-family: var(--font-mono);
  font-size: 11px;
  text-align: center;
  margin: 8px 20px 0;
}
.transcript-status.error { color: var(--danger); }
.transcript-status.success { color: var(--accent-ink); }
</style>
