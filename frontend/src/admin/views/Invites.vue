<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { onMounted, ref } from 'vue'
import AdminLayout from './AdminLayout.vue'
import ConfirmDialog from '../../theme/components/ConfirmDialog.vue'
import EmptyState from '../../theme/components/EmptyState.vue'
import { invitesApi } from '../../interfaces/api/resources'
import type { Invite } from '../../interfaces/api/types'
import { ApiError } from '../../interfaces/api/client'
import { useToastStore } from '../../core/stores/toast'

const toast = useToastStore()
const rows = ref<Invite[]>([])
const loading = ref(true)
const count = ref(5)
const maxUses = ref(1)
const note = ref('')
const busy = ref(false)
const fresh = ref<string[]>([])
const revoke = ref<Invite | null>(null)

async function load() {
  loading.value = true
  try { rows.value = await invitesApi.list() }
  catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { loading.value = false }
}
async function generate() {
  busy.value = true
  try {
    fresh.value = await invitesApi.create({ count: count.value, max_uses: maxUses.value, note: note.value || null })
    toast.show(`已生成 ${fresh.value.length} 个邀请码，请立即保存`, 'success', 4000)
    note.value = ''
    await load()
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { busy.value = false }
}
async function copyAll() {
  try { await navigator.clipboard.writeText(fresh.value.join('\n')); toast.show('已复制全部邀请码', 'success') }
  catch { toast.show('复制失败，请手动选择', 'error') }
}
async function doRevoke() {
  if (!revoke.value) return
  try { await invitesApi.revoke(revoke.value.id); await load(); toast.show('邀请码已作废', 'success') }
  catch (e) { toast.show((e as ApiError).message, 'error') }
  revoke.value = null
}
function expired(i: Invite) { return !!i.expires_at && new Date(i.expires_at) < new Date() }
onMounted(load)
</script>

<template>
  <AdminLayout>
    <header class="head"><div><h1>邀请码发放</h1><p>完整邀请码只在生成时显示一次，列表仅展示掩码</p></div></header>

    <section class="card gen">
      <div class="two">
        <div><label class="fl">生成数量</label><input v-model.number="count" class="fi" type="number" min="1" max="100" /></div>
        <div><label class="fl">每码可用次数</label><input v-model.number="maxUses" class="fi" type="number" min="1" /></div>
      </div>
      <label class="fl">备注</label><input v-model="note" class="fi" placeholder="例如：首批内测" />
      <button class="primary" :disabled="busy" @click="generate">{{ busy ? '生成中…' : '批量生成' }}</button>
    </section>

    <section v-if="fresh.length" class="card fresh">
      <div class="fh"><b>本次生成（仅此一次显示）</b><button class="ghost" @click="copyAll">复制全部</button></div>
      <code v-for="c in fresh" :key="c" class="code">{{ c }}</code>
    </section>

    <p v-if="loading" class="hint">加载中…</p>
    <EmptyState v-else-if="!rows.length" icon="key" title="还没有邀请码" desc="生成后即可发放给新用户注册" />
    <section v-for="i in rows" :key="i.id" class="card row">
      <div class="top">
        <code class="masked">{{ i.code_masked }}</code>
        <span class="tag" :class="{ off: expired(i) || i.used_count >= i.max_uses }">
          {{ expired(i) ? '已作废' : i.used_count >= i.max_uses ? '已用完' : '可用' }}
        </span>
      </div>
      <div class="meta">
        <span class="pill">已用 {{ i.used_count }} / {{ i.max_uses }}</span>
        <span v-if="i.note" class="pill">{{ i.note }}</span>
        <span class="pill">{{ new Date(i.created_at).toLocaleDateString() }}</span>
      </div>
      <div class="acts">
        <button class="ghost danger" :disabled="expired(i)" @click="revoke = i">
          <AppIcon name="ban" />作废
        </button>
      </div>
    </section>

    <ConfirmDialog :open="!!revoke" title="作废邀请码" danger
                   message="作废后该邀请码立即不可用于注册，已注册的账号不受影响。"
                   @close="revoke = null" @confirm="doRevoke" />
  </AdminLayout>
</template>

<style scoped>
.head { padding: 14px 16px 10px; }
.head h1 { font-size: var(--fs-xl); font-weight: 700; }
.head p { font-size: var(--fs-cap); color: var(--t3); margin-top: 3px; }
.card { margin: 10px 16px 0; padding: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 8px 0 4px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.two { display: flex; gap: 8px; }
.two > div { flex: 1; min-width: 0; }
.primary { width: 100%; margin-top: 12px; padding: 11px 0; border: none; border-radius: var(--r-sm);
  background: var(--accent); color: #fff; font-size: var(--fs-md); font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .5; }
.fresh { border-color: var(--accent); background: var(--accent-soft); }
.fh { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-size: var(--fs-sm); }
.code { display: block; font-family: ui-monospace, Menlo, monospace; font-size: var(--fs-md);
  padding: 5px 0; color: var(--t1); }
.hint { padding: 24px; text-align: center; color: var(--t4); }
.top { display: flex; align-items: center; justify-content: space-between; }
.masked { font-family: ui-monospace, Menlo, monospace; font-size: var(--fs-md); font-weight: 700; }
.tag { font-size: 10px; padding: 2px 7px; border-radius: 3px; background: var(--ok-soft); color: var(--ok); font-weight: 700; }
.tag.off { background: var(--fill); color: var(--t3); }
.meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.pill { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: var(--surface-2); border: 1px solid var(--line); color: var(--t3); }
.acts { margin-top: 9px; }
.ghost { display: inline-flex; align-items: center; gap: 3px; padding: 6px 9px; border: 1px solid var(--line-2);
  background: var(--surface); color: var(--t2); border-radius: var(--r-sm); font-size: var(--fs-cap); cursor: pointer; }
.ghost .app-icon { width: 14px; height: 14px; }
.ghost:disabled { opacity: .45; cursor: not-allowed; }
.ghost.danger:hover { border-color: var(--err); color: var(--err); }
</style>
