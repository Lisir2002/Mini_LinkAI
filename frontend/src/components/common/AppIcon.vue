<script setup lang="ts">
/**
 * 自绘 SVG 图标。所有图形来自 src/icons，不使用任何图标字体或外部图标库。
 * 颜色继承 currentColor，尺寸由 size 控制，描边粗细可按场景微调。
 */
import { computed } from 'vue'
import { resolveIcon } from '../../icons'

const props = withDefaults(defineProps<{
  name: string
  size?: number
  stroke?: number
  title?: string
}>(), { size: 20, stroke: 1.7 })

const shapes = computed(() => resolveIcon(props.name))
</script>

<template>
  <svg class="app-icon" :width="size" :height="size" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" :stroke-width="stroke" stroke-linecap="round" stroke-linejoin="round"
       :role="title ? 'img' : undefined" :aria-hidden="title ? undefined : 'true'"
       :aria-label="title" focusable="false">
    <title v-if="title">{{ title }}</title>
    <component :is="s.tag" v-for="(s, i) in shapes" :key="i" v-bind="s.attrs" />
  </svg>
</template>

<style scoped>
.app-icon { display: inline-block; flex-shrink: 0; vertical-align: middle; overflow: visible; }
</style>
