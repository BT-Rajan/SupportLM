<template>
  <div class="escalation">
    <p class="escalation-label">I couldn't fully answer that. Want a team member to follow up? Enter your email:</p>
    <div class="escalation-row">
      <input
        v-model="email"
        type="email"
        class="escalation-email"
        placeholder="you@example.com"
        :disabled="submitting || done"
        @keydown.enter.prevent="submit"
      />
      <button type="button" class="escalation-submit" :disabled="submitting || done" @click="submit">
        {{ done ? "Sent" : "Submit" }}
      </button>
    </div>
    <p v-if="status" class="escalation-status" :class="statusKind">{{ status }}</p>
  </div>
</template>

<script setup>
import { ref } from "vue";

const props = defineProps({
  messageId: { type: [Number, String], required: true },
  onEscalate: { type: Function, required: true },
});

const email = ref("");
const submitting = ref(false);
const done = ref(false);
const status = ref("");
const statusKind = ref("");

async function submit() {
  if (done.value) return;
  const value = email.value.trim();
  if (!value) {
    status.value = "Please enter an email address.";
    statusKind.value = "error";
    return;
  }
  submitting.value = true;
  status.value = "";
  try {
    const result = await props.onEscalate(props.messageId, value);
    status.value = `Support request ${result.sr_number} created — check your email.`;
    statusKind.value = "success";
    done.value = true;
  } catch (err) {
    status.value = err.message || "Could not create a support request.";
    statusKind.value = "error";
  } finally {
    submitting.value = false;
  }
}
</script>

<style scoped>
.escalation {
  margin-top: 10px;
  padding: 12px 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-alt);
}
.escalation-label { font-size: 12.5px; color: var(--muted); margin: 0 0 9px; line-height: 1.45; }
.escalation-row { display: flex; gap: 7px; }
.escalation-email {
  flex: 1;
  min-width: 0;
  height: 34px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--surface);
  padding: 0 11px;
  font-size: 13px;
  font-family: var(--font-body);
  outline: none;
  transition: border-color 0.15s ease;
}
.escalation-email:focus { border-color: var(--accent); }
.escalation-submit {
  height: 34px;
  padding: 0 15px;
  border-radius: 9px;
  border: none;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease;
}
.escalation-submit:hover:not(:disabled) { background: var(--accent-ink); }
.escalation-submit:disabled { opacity: 0.65; cursor: not-allowed; }
.escalation-status { margin: 7px 0 0; font-size: 12px; }
.escalation-status.error { color: var(--danger); }
.escalation-status.success { color: var(--accent-ink); }
</style>
