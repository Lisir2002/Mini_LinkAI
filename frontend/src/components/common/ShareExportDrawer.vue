<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import Drawer from './Drawer.vue'
import { onMounted, ref, watch } from 'vue'
import { downloadExport, sharesApi, type ShareItem } from '../../api/resources'
import { useToastStore } from '../../stores/toast'

const props = defineProps<{ open: boolean; scope: 'dm' | 'room'; targetId: number; title: string }>()
const emit = defineEmits<{ close: [] }>()
const toast = useToastStore()
const days = ref(7)
const creating = ref(false)
const shares = ref<ShareItem[]>([])
const loading = ref(false)

async function loadShares() {
  loading.value = true
  try {
    const all = await sharesApi.list()
    shares.value = all.filter((s) =>
      props.scope === 'dm' ? s.conversation_id === props.targetId : s.room_id === props.targetId)
  } catch { shares.value = [] }
  finally { loading.value = false }
}

watch(() => props.open, (v) => { if (v) void loadShares() })
onMounted(() => { if (props.open) void loadShares() })

async function doExport(format: 'md' | 'json') {
  const path = props.scope === 'dm'
    ? `/api/conversations/${props.targetId}/export?format=${format}`
    : `/api/rooms/${props.targetId}/export?format=${format}`
  try {
    await downloadExport(path, `${props.title}.${format}`)
    toast.show('导出已开始下载', 'success')
  } catch (e: any) { toast.show(e.message ?? '导出失败', 'error') }
}

function shareUrl(token: string) {
  return `${location.origin}/s/${token}`
}

async function createShare() {
  creating.value = true
  try {
    const body = props.scope === 'dm'
      ? { scope: 'dm' as const, conversation_id: props.targetId, days: days.value }
      : { scope: 'room' as const, room_id: props.targetId, days: days.value }
    const d = await sharesApi.create(body)
    await copyLink(d.token)
    await loadShares()
  } catch (e: any) { toast.show(e.message ?? '创建分享失败', 'error') }
  finally { creating.value = false }
}

async function copyLink(token: string) {
  try {
    await navigator.clipboard.writeText(shareUrl(token))
    toast.show('分享链接已复制', 'success')
  } catch { toast.show('复制失败，请长按链接手动复制', 'error') }
}

async function revoke(s: ShareItem) {
  try { await sharesApi.revoke(s.id); await loadShares(); toast.show('已撤销分享') }
  catch (e: any) { toast.show(e.message ?? '撤销失败', 'error') }
}

function when(iso: string) { return new Date(iso).toLocaleDateString() }
</script>

<template>
  <Drawer :open="open" title="导出与分享" desc="导出当前记录，或生成免登录只读链接" @close="emit('close')">
    <label class="fl">导出</label>
    <div class="exp-row">
      <button class="exp" @click="doExport('md')"><AppIcon name="download" />Markdown</button>
      <button class="exp" @click="doExport('json')"><AppIcon name="download" />JSON</button>
    </div>

    <label class="fl">创建只读分享</label>
    <div class="share-row">
      <select v-model.number="days" class="fi days">
        <option :value="1">1 天有效</option>
        <option :value="7">7 天有效</option>
        <option :value="30">30 天有效</option>
      </select>
      <button class="primary sm" :disabled="creating" @click="createShare">
        <AppIcon name="link" />{{ creating ? '创建中…' : '创建并复制链接' }}
      </button>
    </div>

    <label class="fl">已创建的分享</label>
    <p v-if="loading" class="hint">加载中…</p>
    <p v-else-if="!shares.length" class="hint">还没有分享链接。</p>
    <div v-for="s in shares" :key="s.id" class="sitem" :class="{ off: s.revoked }">
      <div class="smain">
        <span class="stoken">{{ shareUrl(s.token) }}</span>
        <span class="smeta">{{ s.revoked ? '已撤销' : `${when(s.expires_at)} 到期` }}</span>
      </div>
      <button v-if="!s.revoked" class="mini" aria-label="复制链接" @click="copyLink(s.token)">
        <AppIcon name="copy" />
      </button>
      <button v-if="!s.revoked" class="mini danger" aria-label="撤销分享" @click="revoke(s)">
        <AppIcon name="ban" />
      </button>
    </div>
  </Drawer>
</template>

<style scoped>
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 12px 0 6px; }
.exp-row { display: flex; gap: 8px; }
.exp { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 10px 0; border: 1px solid var(--line); border-radius: var(--r-sm);
  background: var(--surface); color: var(--t1); font-size: var(--fs-md); cursor: pointer; }
.exp .app-icon { width: 16px; height: 16px; color: var(--accent); }
.share-row { display: flex; gap: 8px; align-items: center; }
.fi { padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.days { flex-shrink: 0; }
.primary { display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; border: none;
  border-radius: var(--r-sm); background: var(--accent); color: #fff; font-size: var(--fs-md);
  font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .5; }
.primary .app-icon { width: 15px; height: 15px; }
.hint { font-size: var(--fs-sm); color: var(--t4); padding: 6px 0; }
.sitem { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border: 1px solid var(--line);
  border-radius: var(--r-sm); margin-bottom: 6px; background: var(--surface); }
.sitem.off { opacity: .55; }
.smain { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.stoken { font-size: var(--fs-cap); color: var(--t2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.smeta { font-size: 10px; color: var(--t4); }
.mini { background: none; border: none; color: var(--t3); cursor: pointer; padding: 4px; }
.mini .app-icon { width: 16px; height: 16px; }
.mini.danger:hover { color: var(--err); }
</style>