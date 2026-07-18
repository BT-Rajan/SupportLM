<template>
  <ChatWidget :tenant-slug="config.tenant_slug" :theme="config.theme || {}" />
</template>

<script setup>
import ChatWidget from "./components/ChatWidget.vue";

defineProps({
  config: { type: Object, default: () => ({}) },
});
</script>
