<template>
  <section class="panel">
    <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:6px;">
      <div style="display:flex; align-items:center; gap:10px;">
        <label class="field-label" style="margin:0;" for="range-select">Range</label>
        <select id="range-select" v-model.number="days" class="field-input">
          <option :value="7">Last 7 days</option>
          <option :value="30">Last 30 days</option>
          <option :value="90">Last 90 days</option>
        </select>
      </div>
      <a class="btn-ghost" :href="exportUrl" download>Download CSV</a>
    </div>

    <div v-if="dash" class="stat-grid">
      <div class="stat-card"><div class="stat-value">{{ dash.conversation_count }}</div><div class="stat-label">Conversations</div></div>
      <div class="stat-card"><div class="stat-value">{{ dash.answer_count }}</div><div class="stat-label">Answers</div></div>
      <div class="stat-card"><div class="stat-value">{{ dash.escalation_count }}</div><div class="stat-label">Escalations</div></div>
      <div class="stat-card"><div class="stat-value">{{ dash.csat.percentage === null ? "—" : dash.csat.percentage + "%" }}</div><div class="stat-label">CSAT</div></div>
      <div class="stat-card"><div class="stat-value">${{ Number(dash.cost.total_usd).toFixed(4) }}</div><div class="stat-label">Est. cost</div></div>
      <div class="stat-card"><div class="stat-value">{{ dash.flagged_question_count }}</div><div class="stat-label">Flagged</div></div>
    </div>

    <h3 class="panel-subtitle">Answers per day</h3>
    <div class="chart-wrap">
      <BarChart v-if="dash" :values="volumeValues" :height="120" aria-label="Answers per day" empty-text="No answers in this range yet." />
    </div>

    <h3 class="panel-subtitle">Estimated LLM cost by model</h3>
    <div class="chart-wrap">
      <BarChart v-if="dash" :values="costValues" :height="100" aria-label="Estimated cost by model" empty-text="No usage recorded in this range yet." />
    </div>

    <h3 class="panel-subtitle">Flagged questions</h3>
    <ul v-if="flagged.length" class="plain-list">
      <li v-for="f in flagged" :key="f.message_id" style="display:block;">
        <span class="badge badge-error" style="margin-right:8px;">{{ f.reasons.join(", ") }}</span>
        <span>{{ snippet(f.content) }}</span>
      </li>
    </ul>
    <p v-else class="empty-state">
      <span class="empty-title">Nothing flagged</span>
      <span class="empty-body">Escalated or low-confidence answers in this range will show up here.</span>
    </p>
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue";
import BarChart from "./BarChart.vue";
import { useAdminApi, ApiError } from "../composables/useAdminApi.js";
import { useToast } from "../composables/useToast.js";

const props = defineProps({ tenantSlug: { type: String, required: true } });
const { api, base } = useAdminApi(props.tenantSlug);
const toast = useToast();

const days = ref(30);
const dash = ref(null);
const flagged = ref([]);

const exportUrl = computed(() => `${base}/api/tenant/analytics/export.csv?days=${days.value}`);

const volumeValues = computed(() =>
  dash.value
    ? dash.value.daily_volume.map((d) => ({ label: d.date, shortLabel: d.date.slice(5), value: d.count }))
    : []
);
const costValues = computed(() =>
  dash.value
    ? dash.value.cost.by_provider_model.map((c) => ({
        label: `${c.provider}/${c.model}`,
        shortLabel: c.model,
        value: Number(c.estimated_cost_usd),
      }))
    : []
);

function snippet(text) {
  return text.length > 140 ? text.slice(0, 140) + "…" : text;
}

async function load() {
  try {
    const [dashData, flaggedData] = await Promise.all([
      api(`/api/tenant/analytics/dashboard?days=${days.value}`),
      api(`/api/tenant/analytics/flagged-questions?days=${days.value}`),
    ]);
    dash.value = dashData;
    flagged.value = flaggedData;
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : "Could not load analytics.");
  }
}

watch(days, load);
onMounted(load);
</script>
