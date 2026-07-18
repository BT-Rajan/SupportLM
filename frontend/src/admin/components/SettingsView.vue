<template>
  <LlmConfigPanel :api="api" />
  <PromptVersionsPanel :api="api" />
  <SupportConfigPanel :api="api" />
  <ApiKeysPanel :api="api" />
</template>

<script setup>
import LlmConfigPanel from "./settings/LlmConfigPanel.vue";
import PromptVersionsPanel from "./settings/PromptVersionsPanel.vue";
import SupportConfigPanel from "./settings/SupportConfigPanel.vue";
import ApiKeysPanel from "./settings/ApiKeysPanel.vue";
import { useAdminApi } from "../composables/useAdminApi.js";

const props = defineProps({ tenantSlug: { type: String, required: true } });
const { api } = useAdminApi(props.tenantSlug);
</script>
