<script setup lang="ts">
defineProps<{ title: string; sub?: string }>()
</script>
<template>
  <header class="navbar">
    <slot name="left" />
    <div class="nav-title-wrap">
      <div class="navbar-title">{{ title }}</div>
      <div v-if="sub" class="nav-sub">{{ sub }}</div>
    </div>
    <div class="nav-right"><slot name="right" /></div>
  </header>
</template>
<style scoped>
.navbar {
  display: flex; align-items: center; gap: 4px; padding: 8px 12px; min-height: 46px;
  background: var(--surface); border-bottom: 1px solid var(--line);
}
.navbar-title { font-size: var(--fs-xl); font-weight: 700; }
.nav-sub { font-size: 10px; color: var(--t3); margin-top: -2px; }
.nav-title-wrap { flex: 1; min-width: 0; }
.nav-right { display: flex; align-items: center; gap: 2px; }
</style>
