<template>
  <span class="aura" :class="{ 'aura-thinking': thinking, [`aura-${size}`]: true }" aria-hidden="true">
    <span class="aura-ring"></span>
    <span class="aura-core">
      <img v-if="logoUrl" class="aura-logo" :src="logoUrl" :alt="''" />
      <span v-else class="aura-mono">{{ monogram }}</span>
    </span>
  </span>
</template>

<script setup>
defineProps({
  monogram: { type: String, default: "S" },
  logoUrl: { type: String, default: null },
  thinking: { type: Boolean, default: false },
  size: { type: String, default: "md" }, // 'sm' | 'md'
});
</script>

<style scoped>
/* The recurring signature motif of this rebuild: every brand touchpoint
   (header mark, each assistant reply, the "composing" state) is the
   same avatar with a thin conic-gradient ring around it. At rest the
   ring is a static hairline; while the assistant is composing, it
   rotates slowly — replacing the old three-dot typing bubble with
   something that reads as "the brand is at work" rather than a
   generic loading spinner. */
.aura {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.aura-md { width: 36px; height: 36px; }
.aura-sm { width: 24px; height: 24px; }

.aura-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  padding: 1.5px;
  background: conic-gradient(from 0deg, var(--accent) 0deg, var(--accent-soft) 140deg, transparent 200deg, var(--accent) 360deg);
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0.9;
}

.aura-thinking .aura-ring {
  animation: aura-spin 1.6s linear infinite;
}

@keyframes aura-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .aura-thinking .aura-ring { animation: none; opacity: 0.55; }
}

.aura-core {
  position: absolute;
  inset: 3px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.aura-sm .aura-core { inset: 2px; }

.aura-mono {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 15px;
}
.aura-sm .aura-mono { font-size: 10px; }

.aura-logo {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: var(--surface);
  padding: 2px;
}
</style>
