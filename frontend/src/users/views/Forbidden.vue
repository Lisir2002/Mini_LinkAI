<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { useRouter } from 'vue-router'
const router = useRouter()
</script>
<template>
  <div class="app-container center">
    <AppIcon name="lock" class="big" />
    <h1>没有访问权限</h1>
    <p>该页面仅管理员可见。如需权限请联系系统管理员。</p>
    <button class="primary" @click="router.push('/msgs')">返回消息</button>
  </div>
</template>
<style scoped>
.center { align-items: center; justify-content: center; text-align: center; padding: 32px; gap: 10px; }
.big { font-size: 56px; color: var(--t4); }
h1 { font-size: var(--fs-xl); font-weight: 700; }
p { font-size: var(--fs-sm); color: var(--t3); line-height: 1.6; }
.primary { margin-top: 8px; padding: 10px 24px; border: none; border-radius: var(--r-sm);
  background: var(--accent); color: #fff; font-size: var(--fs-md); font-weight: 600; cursor: pointer; }
</style>
