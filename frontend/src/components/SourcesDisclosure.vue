<template>
  <div v-if="sources && sources.length" class="sources">
    <button
      type="button"
      class="sources-toggle"
      :aria-expanded="open"
      @click="open = !open"
    >
      {{ sources.length }} {{ sources.length === 1 ? "source" : "sources" }}
    </button>
    <div v-show="open" class="sources-list">
      <ul>
        <li v-for="(s, i) in sources" :key="i">{{ s.heading_path || "Untitled section" }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";

defineProps({ sources: { type: Array, default: () => [] } });
const open = ref(false);
</script>

<style scoped>
.sources-toggle {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--accent-ink);
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.sources-list {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--muted);
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}
.sources-list ul { margin: 0; padding-left: 16px; }
.sources-list li { margin-bottom: 3px; }
</style>
