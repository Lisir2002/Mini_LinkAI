<script setup lang="ts">
import AppIcon from '../../components/common/AppIcon.vue'
defineProps<{ open: boolean; title: string; desc?: string }>()
defineEmits<{ close: [] }>()
</script>
<template>
  <teleport to="body">
    <div v-if="open" class="mask" @click="$emit('close')" />
    <section v-if="open" class="drawer" role="dialog" :aria-label="title">
      <div class="handle" />
      <header class="head">
        <div>
          <h2>{{ title }}</h2>
          <p v-if="desc">{{ desc }}</p>
        </div>
        <button type="button" class="close" aria-label="关闭" @click="$emit('close')">
          <AppIcon name="close" />
        </button>
      </header>
      <div class="body"><slot /></div>
      <footer v-if="$slots.footer" class="foot"><slot name="footer" /></footer>
    </section>
  </teleport>
</template>
<style scoped>
.mask { position: fixed; inset: 0; background: var(--mask); z-index: 200; }
.drawer { position: fixed; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 375px;
  max-height: 86dvh; background: var(--surface); border-radius: var(--r-lg) var(--r-lg) 0 0; z-index: 201;
  display: flex; flex-direction: column; }
.handle { width: 32px; height: 3px; background: var(--line-2); border-radius: 2px; margin: 10px auto 4px; }
.head { display: flex; align-items: flex-start; gap: 8px; padding: 6px 16px 10px; }
.head h2 { font-size: var(--fs-lg); font-weight: 700; }
.head p { font-size: var(--fs-cap); color: var(--t3); margin-top: 2px; }
.head > div { flex: 1; min-width: 0; }
.close { background: none; border: none; color: var(--t3); cursor: pointer; padding: 2px; }
.body { padding: 0 16px 12px; overflow-y: auto; flex: 1; }
.foot { padding: 10px 16px calc(14px + env(safe-area-inset-bottom)); border-top: 1px solid var(--line); }
@media (min-width: 1024px) {
  .drawer { left: auto; right: 0; top: 0; bottom: 0; transform: none; max-width: 460px; max-height: 100dvh;
    border-radius: 0; border-left: 1px solid var(--line); }
  .handle { display: none; }
}
</style>
