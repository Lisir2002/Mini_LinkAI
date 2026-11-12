<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { onBeforeUnmount, ref, watch } from 'vue'
import { getToken } from '../../interfaces/api/client'

const props = defineProps<{ uploadId: number; small?: boolean }>()
const src = ref('')
const failed = ref(false)
const zoom = ref(false)
let objectUrl = ''

async function load() {
  failed.value = false
  try {
    const base = import.meta.env?.VITE_API_BASE ?? ''
    const resp = await fetch(`${base}/api/uploads/${props.uploadId}/content`, {
      headers: { ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
    })
    if (!resp.ok) throw new Error('load failed')
    const blob = await resp.blob()
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    objectUrl = URL.createObjectURL(blob)
    src.value = objectUrl
  } catch {
    failed.value = true
  }
}
watch(() => props.uploadId, load, { immediate: true })
onBeforeUnmount(() => { if (objectUrl) URL.revokeObjectURL(objectUrl) })
</script>

<template>
  <span v-if="failed" class="img-fail"><AppIcon name="warning" />图片加载失败</span>
  <img v-else-if="src" :src="src" :class="['auth-img', { small }]" alt="附件图片"
       @click="zoom = true" />
  <span v-else class="img-loading">加载中…</span>
  <Teleport to="body">
    <div v-if="zoom" class="lightbox" @click="zoom = false">
      <img :src="src" alt="附件图片大图" />
    </div>
  </Teleport>
</template>

<style scoped>
.auth-img { display: block; width: min(56vw, 230px); height: auto; max-height: 300px;
  border-radius: 10px; margin-bottom: 6px; cursor: zoom-in; object-fit: cover;
  border: 1px solid var(--line); background: var(--surface-2); }
.auth-img.small { width: 40px; height: 40px; max-height: 40px; margin: 0; cursor: default; }
.img-fail { display: inline-flex; align-items: center; gap: 4px; font-size: 11px;
  color: var(--t4); margin-bottom: 6px; }
.img-fail .app-icon { width: 13px; height: 13px; }
.img-loading { font-size: 11px; color: var(--t4); }
.lightbox { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,.85);
  display: flex; align-items: center; justify-content: center; cursor: zoom-out; }
.lightbox img { max-width: 92vw; max-height: 92vh; border-radius: 6px; }
</style>