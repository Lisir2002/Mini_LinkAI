<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ values: number[]; height?: number }>(), { height: 44 })

const W = 220
const points = computed(() => {
  const vs = props.values
  if (!vs.length) return ''
  const min = Math.min(...vs)
  const max = Math.max(...vs)
  const span = max - min || 1
  const step = vs.length > 1 ? W / (vs.length - 1) : W
  return vs
    .map((v, i) => `${(i * step).toFixed(1)},${(props.height - 4 - ((v - min) / span) * (props.height - 10)).toFixed(1)}`)
    .join(' ')
})
const last = computed(() => {
  const p = points.value
  return p ? p.split(' ').pop()!.split(',') : null
})
</script>

<template>
  <svg class="spark" :viewBox="`0 0 ${W} ${height}`" preserveAspectRatio="none" aria-hidden="true">
    <line x1="0" :y1="height - 4" :x2="W" :y2="height - 4" class="base" />
    <polyline v-if="points" :points="points" class="line" />
    <circle v-if="last" :cx="last[0]" :cy="last[1]" r="2.6" class="tip" />
  </svg>
</template>

<style scoped>
.spark { width: 100%; display: block; }
.base { stroke: var(--line); stroke-width: 1; }
.line { fill: none; stroke: var(--accent); stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.tip { fill: var(--accent); }
</style>