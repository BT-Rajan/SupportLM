<template>
  <div class="console">
    <header class="console-header">
      <div class="brand">
        <BrandAura :monogram="theme.monogram || 'S'" :logo-url="theme.logo_url" size="md" />
        <div class="brand-text">
          <span class="brand-name">{{ theme.display_name || "Support" }}</span>
          <span class="brand-status"><span class="status-dot"></span>Usually replies in seconds</span>
        </div>
      </div>
      <div class="header-actions">
        <LanguageSelect v-model="language" />
        <button
          type="button"
          class="transcript-btn"
          :aria-expanded="transcriptOpen"
          title="Email me this conversation"
          aria-label="Email me this conversation"
          :disabled="!conversationId"
          @click="transcriptOpen = !transcriptOpen"
        >
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true">
            <path d="M3 5.5h14a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.4"/>
            <path d="M2.5 6L10 11L17.5 6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
        <span class="ai-tag">AI&nbsp;assisted</span>
      </div>
    </header>

    <p v-if="limitWarning" class="limit-banner">{{ limitWarning }}</p>

    <main ref="threadEl" class="thread" aria-live="polite">
      <div v-if="messages.length === 0" class="welcome">
        <p class="welcome-title">Hi, how can I help?</p>
        <p class="welcome-body">Ask anything about your account, setup, or billing — answers are pulled straight from our docs.</p>
        <div class="suggestions">
          <button
            v-for="s in suggestions"
            :key="s"
            type="button"
            class="chip"
            @click="submit(s)"
          >{{ s }}</button>
        </div>
      </div>

      <MessageBubble
        v-for="m in messages"
        :key="m.id"
        :message="m"
        :monogram="theme.monogram || 'S'"
        :logo-url="theme.logo_url"
        :on-vote="submitFeedback"
        :on-escalate="submitEscalation"
      />
    </main>

    <TranscriptPanel
      v-if="transcriptOpen"
      :on-send="sendTranscript"
      @close="transcriptOpen = false"
    />

    <form class="composer" @submit.prevent="submitFromInput">
      <textarea
        ref="inputEl"
        v-model="draft"
        class="composer-input"
        placeholder="Type your question…"
        rows="1"
        autocomplete="off"
        aria-label="Message"
        @input="autoResize"
        @keydown.enter.exact.prevent="submitFromInput"
      ></textarea>
      <button type="submit" class="composer-send" aria-label="Send message" :disabled="sending || !draft.trim()">
        <svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true">
          <path d="M2.5 10L17.5 3L12 17.5L9.5 11.5L2.5 10Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
        </svg>
      </button>
    </form>
    <p class="disclaimer">Answers are AI-generated from our knowledge base and may occasionally be wrong.</p>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from "vue";
import BrandAura from "./BrandAura.vue";
import LanguageSelect from "./LanguageSelect.vue";
import MessageBubble from "./MessageBubble.vue";
import TranscriptPanel from "./TranscriptPanel.vue";
import { useChat } from "../composables/useChat.js";

const props = defineProps({
  tenantSlug: { type: String, required: true },
  theme: { type: Object, default: () => ({}) },
});

const suggestions = [
  "What do you offer?",
  "Do you provide customized solutions?",
  "How do I contact support?",
];

const { messages, conversationId, sending, limitWarning, sendQuestion, submitFeedback, submitEscalation, sendTranscript } =
  useChat(props.tenantSlug);

const draft = ref("");
const transcriptOpen = ref(false);
const threadEl = ref(null);
const inputEl = ref(null);

const LANGUAGE_KEY = "supportlm-language-" + props.tenantSlug;
const language = ref(localStorage.getItem(LANGUAGE_KEY) || "en");
watch(language, (v) => {
  try {
    localStorage.setItem(LANGUAGE_KEY, v);
  } catch {
    // localStorage unavailable (private browsing, disabled) — persistence
    // is a nicety, the selector keeps working for this session regardless.
  }
});

function autoResize() {
  const el = inputEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

async function scrollToBottom() {
  await nextTick();
  if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight;
}

async function submit(question) {
  if (!question.trim() || sending.value) return;
  await sendQuestion(question, language.value);
  inputEl.value && inputEl.value.focus();
}

async function submitFromInput() {
  const q = draft.value.trim();
  if (!q || sending.value) return;
  draft.value = "";
  await nextTick();
  autoResize();
  await submit(q);
}

watch(messages, scrollToBottom, { deep: true });
</script>

<style scoped>
.console {
  width: 100%;
  max-width: 640px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-elevated);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.console-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 17px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.brand { display: flex; align-items: center; gap: 13px; min-width: 0; }
.brand-text { display: flex; flex-direction: column; line-height: 1.35; min-width: 0; }
.brand-name {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 16.5px;
  letter-spacing: 0.005em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.brand-status {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--live);
  box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.55);
  animation: pulse 2.2s ease-out infinite;
  flex-shrink: 0;
}
@keyframes pulse {
  0%   { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5); }
  70%  { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); }
  100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
}
@media (prefers-reduced-motion: reduce) {
  .status-dot { animation: none; }
}

.header-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.ai-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.02em;
  color: var(--accent-ink);
  background: var(--accent-soft);
  border-radius: 999px;
  padding: 4px 10px;
  white-space: nowrap;
}

.transcript-btn {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.transcript-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent-ink); }
.transcript-btn[aria-expanded="true"] { border-color: var(--accent); color: var(--accent-ink); background: var(--accent-soft); }
.transcript-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.limit-banner {
  margin: 0;
  padding: 8px 20px;
  font-size: 12px;
  color: var(--accent-ink);
  background: var(--accent-soft);
  border-bottom: 1px solid var(--border);
}

.thread {
  flex: 1;
  min-height: 380px;
  max-height: 62vh;
  overflow-y: auto;
  padding: 22px 20px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--surface-alt);
}

.welcome { margin: auto 0; text-align: left; padding: 4px 4px 8px; }
.welcome-title { font-family: var(--font-display); font-size: 22px; font-weight: 600; margin: 0 0 7px; }
.welcome-body { font-size: 14px; color: var(--muted); margin: 0 0 18px; max-width: 42ch; line-height: 1.5; }

.suggestions { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.chip {
  font-family: var(--font-body);
  font-size: 13px;
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 13px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, transform 0.1s ease, box-shadow 0.15s ease;
}
.chip:hover { border-color: var(--accent); box-shadow: var(--shadow-card); }
.chip:active { transform: scale(0.98); }

.composer {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 15px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.composer-input {
  flex: 1;
  resize: none;
  max-height: 120px;
  font-family: var(--font-body);
  font-size: 14.5px;
  line-height: 1.4;
  padding: 11px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
  background: var(--surface-alt);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.composer-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }

.composer-send {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  border-radius: var(--radius-sm);
  border: none;
  background: var(--accent);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.1s ease;
}
.composer-send:hover:not(:disabled) { background: var(--accent-ink); }
.composer-send:active:not(:disabled) { transform: scale(0.94); }
.composer-send:disabled { background: var(--border); cursor: not-allowed; }

.disclaimer {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--muted);
  text-align: center;
  margin: 11px 0 0;
}

@media (max-width: 480px) {
  .console { max-width: 100%; min-height: 100vh; border-radius: 0; border: none; }
  .thread { max-height: none; }
}
</style>
