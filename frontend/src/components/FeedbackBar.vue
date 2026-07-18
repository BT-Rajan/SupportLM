<template>
  <div class="feedback-bar">
    <button
      type="button"
      class="feedback-btn"
      :class="{ selected: voted === 'up' }"
      :disabled="!!voted"
      aria-label="Helpful"
      @click="vote('up')"
    >👍</button>
    <button
      type="button"
      class="feedback-btn"
      :class="{ selected: voted === 'down' }"
      :disabled="!!voted"
      aria-label="Not helpful"
      @click="vote('down')"
    >👎</button>
  </div>
</template>

<script setup>
import { ref } from "vue";

const props = defineProps({
  messageId: { type: [Number, String], required: true },
  onVote: { type: Function, required: true },
});

const voted = ref(null);

function vote(rating) {
  if (voted.value) return;
  voted.value = rating;
  props.onVote(props.messageId, rating);
}
</script>

<style scoped>
.feedback-bar { display: flex; align-items: center; gap: 2px; margin-left: auto; }
.feedback-btn {
  background: none;
  border: none;
  padding: 3px 4px;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.5;
  border-radius: 6px;
  transition: opacity 0.15s ease, background 0.15s ease;
}
.feedback-btn:hover:not(:disabled) { opacity: 0.9; background: var(--surface-alt); }
.feedback-btn:disabled { cursor: default; }
.feedback-btn.selected { opacity: 1; }
</style>
