<template>
  <svg v-if="values.length" :viewBox="`0 0 ${width} ${height}`" width="100%" :height="height" role="img" :aria-label="ariaLabel">
    <rect
      v-for="(v, i) in bars"
      :key="i"
      :x="v.x"
      :y="v.y"
      :width="v.w"
      :height="v.h"
      rx="3"
      fill="var(--accent)"
    >
      <title>{{ v.label }}: {{ v.value }}</title>
    </rect>
    <text
      v-for="(v, i) in bars"
      :key="'t' + i"
      :x="v.x + v.w / 2"
      :y="height - 4"
      font-size="9.5"
      text-anchor="middle"
      fill="var(--muted)"
    >{{ v.shortLabel }}</text>
  </svg>
  <p v-else class="hint">{{ emptyText }}</p>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  values: { type: Array, default: () => [] }, // [{label, shortLabel, value}]
  height: { type: Number, default: 120 },
  emptyText: { type: String, default: "No data in this range yet." },
  ariaLabel: { type: String, default: "Bar chart" },
});

const width = 560;
const barGap = 6;

const bars = computed(() => {
  const max = Math.max(1, ...props.values.map((v) => v.value));
  const barWidth = props.values.length ? (width - barGap * (props.values.length - 1)) / props.values.length : width;
  return props.values.map((v, i) => {
    const h = Math.round((v.value / max) * (props.height - 20));
    return {
      x: i * (barWidth + barGap),
      y: props.height - h - 16,
      w: Math.max(1, barWidth),
      h,
      label: v.label,
      shortLabel: v.shortLabel || "",
      value: v.value,
    };
  });
});
</script>
