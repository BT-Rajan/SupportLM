<template>
  <div class="toast-host">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="`toast-${t.kind}`">
      <span>{{ t.message }}</span>
      <button type="button" class="toast-close" aria-label="Dismiss" @click="dismiss(t.id)">✕</button>
    </div>
  </div>
</template>

<script setup>
import { useToast } from "../composables/useToast.js";
const { toasts, dismiss } = useToast();
</script>

<style scoped>
.toast-host {
  position: fixed;
  right: 20px;
  bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 100;
  width: min(340px, calc(100vw - 40px));
}
.toast {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--muted);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-elevated);
  padding: 12px 14px;
  font-size: 13.5px;
  animation: toast-in 0.2s var(--ease-out);
}
@keyframes toast-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.toast-success { border-left-color: var(--accent); }
.toast-error { border-left-color: var(--danger); }
.toast-close {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
  padding: 2px;
}
</style>
