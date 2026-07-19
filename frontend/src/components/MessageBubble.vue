<template>
  <div class="row" :class="`row-${message.role}`">
    <BrandAura
      v-if="message.role === 'assistant' || message.role === 'pending'"
      class="row-avatar"
      size="sm"
      :monogram="monogram"
      :logo-url="logoUrl"
      :thinking="message.role === 'pending'"
    />

    <div class="bubble-col">
      <div
        class="msg"
        :class="`msg-${message.role}`"
      >
        <template v-if="message.role === 'pending'">
          <span class="composing">Composing a reply…</span>
        </template>
        <template v-else>{{ message.text }}</template>
      </div>

      <div v-if="message.role === 'user' || message.role === 'assistant'" class="meta-row">
        <span class="timestamp">{{ formatTime(message.ts) }}</span>
        <SourcesDisclosure v-if="message.role === 'assistant'" :sources="message.sources" />
        <FeedbackBar
          v-if="message.role === 'assistant' && message.messageId"
          :message-id="message.messageId"
          :on-vote="onVote"
        />
      </div>

      <EscalationPanel
        v-if="message.role === 'assistant' && message.needsEscalation"
        :message-id="message.messageId"
        :on-escalate="onEscalate"
      />
    </div>
  </div>
</template>

<script setup>
import BrandAura from "./BrandAura.vue";
import FeedbackBar from "./FeedbackBar.vue";
import SourcesDisclosure from "./SourcesDisclosure.vue";
import EscalationPanel from "./EscalationPanel.vue";

defineProps({
  message: { type: Object, required: true },
  monogram: { type: String, default: "S" },
  logoUrl: { type: String, default: null },
  onVote: { type: Function, required: true },
  onEscalate: { type: Function, required: true },
});

function formatTime(date) {
  if (!date) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
</script>

<style scoped>
.row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 16px;
  animation: rise 0.28s var(--ease-out);
}
@keyframes rise {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .row { animation: none; }
}

.row-user { justify-content: flex-end; }
.row-assistant, .row-pending { justify-content: flex-start; }

.row-avatar { margin-top: 2px; }

.bubble-col { max-width: 78%; display: flex; flex-direction: column; }
.row-user .bubble-col { align-items: flex-end; }

.msg {
  padding: 11px 14px;
  border-radius: var(--radius);
  font-size: 14.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-user {
  background: var(--accent);
  color: #fff;
  border-bottom-right-radius: 5px;
}

.msg-assistant {
  background: var(--surface);
  border: 1px solid var(--border);
  border-bottom-left-radius: 5px;
  box-shadow: var(--shadow-card);
}

.msg-pending {
  background: var(--surface);
  border: 1px solid var(--border);
  border-bottom-left-radius: 5px;
}
.composing {
  font-size: 13px;
  color: var(--muted);
  font-style: italic;
}

.msg-error {
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  color: var(--danger);
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  padding: 0 2px;
}

.timestamp {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--muted);
  opacity: 0.85;
}
</style>
