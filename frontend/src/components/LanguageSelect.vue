<template>
  <select
    class="language-select"
    title="Reply language"
    aria-label="Reply language"
    :value="modelValue"
    @change="$emit('update:modelValue', $event.target.value)"
  >
    <option value="en">English</option>
    <option value="es">Español</option>
    <option value="fr">Français</option>
    <option value="de">Deutsch</option>
    <option value="ar">العربية</option>
    <option value="hi">हिन्दी</option>
    <option value="zh">中文</option>
    <option value="pt">Português</option>
    <option value="ja">日本語</option>
    <option value="ru">Русский</option>
  </select>
</template>

<script setup>
defineProps({ modelValue: { type: String, default: "en" } });
defineEmits(["update:modelValue"]);
</script>

<style scoped>
.language-select {
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--muted);
  font-family: var(--font-body);
  font-size: 12px;
  padding: 0 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease;
}
.language-select:hover, .language-select:focus { border-color: var(--accent); color: var(--accent-ink); }
</style>
