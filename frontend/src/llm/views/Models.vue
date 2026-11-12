<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import AdminLayout from '../../admin/views/AdminLayout.vue'
import Drawer from '../../theme/components/Drawer.vue'
import Switch from '../../theme/components/Switch.vue'
import ConfirmDialog from '../../theme/components/ConfirmDialog.vue'
import EmptyState from '../../theme/components/EmptyState.vue'
import { channelsApi, modelsApi } from '../../interfaces/api/resources'
import type { Channel, Model } from '../../interfaces/api/types'
import { ApiError } from '../../interfaces/api/client'
import { useToastStore } from '../../core/stores/toast'

const toast = useToastStore()
const rows = ref<Model[]>([])
const channels = ref<Channel[]>([])
const loading = ref(true)
const q = ref('')
const open = ref(false)
const editing = ref<Model | null>(null)
const busy = ref(false)
const binding = ref<Model | null>(null)
const bindChannel = ref<number | null>(null)
const bindUpstream = ref('')
const del = ref<Model | null>(null)

const form = reactive({ public_name: '', display_name: '', tier: 'standard',
  context_limit: 32768, max_output_tokens: 4096, price_input: 0, price_output: 0 })

const filtered = computed(() => rows.value.filter((m) => !q.value.trim()
  || m.public_name.includes(q.value.trim()) || m.display_name.includes(q.value.trim())))

async function load() {
  loading.value = true
  try {
    const [ms, cs] = await Promise.all([modelsApi.list(), channelsApi.list()])
    rows.value = ms; channels.value = cs
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { loading.value = false }
}
function openCreate() {
  editing.value = null
  Object.assign(form, { public_name: '', display_name: '', tier: 'standard',
    context_limit: 32768, max_output_tokens: 4096, price_input: 0, price_output: 0 })
  open.value = true
}
function openEdit(m: Model) {
  editing.value = m
  Object.assign(form, { public_name: m.public_name, display_name: m.display_name, tier: m.tier,
    context_limit: m.context_limit, max_output_tokens: m.max_output_tokens,
    price_input: Number(m.price_input), price_output: Number(m.price_output) })
  open.value = true
}
async function save() {
  if (!form.public_name.trim() || !form.display_name.trim()) { toast.show('对外名与显示名必填', 'error'); return }
  busy.value = true
  try {
    if (editing.value) {
      const u = await modelsApi.patch(editing.value.id, { version: editing.value.version,
        display_name: form.display_name, tier: form.tier, context_limit: form.context_limit,
        max_output_tokens: form.max_output_tokens, price_input: form.price_input, price_output: form.price_output })
      rows.value = rows.value.map((m) => (m.id === u.id ? u : m))
      toast.show('模型已更新', 'success')
    } else {
      rows.value.unshift(await modelsApi.create({ ...form }))
      toast.show('模型已创建，记得绑定渠道', 'success')
    }
    open.value = false
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { busy.value = false }
}
async function setDefault(m: Model) {
  try { await modelsApi.setDefault(m.public_name); await load(); toast.show(`${m.public_name} 已设为默认`, 'success') }
  catch (e) { toast.show((e as ApiError).message, 'error') }
}
async function toggleEnabled(m: Model, v: boolean) {
  try {
    const u = await modelsApi.patch(m.id, { version: m.version, enabled: v })
    rows.value = rows.value.map((x) => (x.id === u.id ? u : x))
  } catch (e) { toast.show((e as ApiError).message, 'error'); await load() }
}
function openBind(m: Model) {
  binding.value = m
  bindChannel.value = channels.value[0]?.id ?? null
  bindUpstream.value = ''
}
async function doBind() {
  if (!binding.value || !bindChannel.value || !bindUpstream.value.trim()) {
    toast.show('请选择渠道并填写上游模型名', 'error'); return
  }
  try {
    await modelsApi.bind(binding.value.id, bindChannel.value, bindUpstream.value.trim())
    toast.show('绑定成功，用户端即可选用该模型', 'success')
    binding.value = null
  } catch (e) { toast.show((e as ApiError).message, 'error') }
}
async function doDelete() {
  if (!del.value) return
  try {
    await modelsApi.remove(del.value.id)
    rows.value = rows.value.filter((m) => m.id !== del.value!.id)
    toast.show('模型已删除，历史用量的模型名快照仍保留', 'success')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  del.value = null
}
onMounted(load)
</script>

<template>
  <AdminLayout>
    <header class="head">
      <div><h1>模型注册表</h1><p>对外模型名与上游解耦，一个对外名可绑多个渠道做故障转移</p></div>
      <button class="primary sm" @click="openCreate"><AppIcon name="plus" />新建模型</button>
    </header>
    <div class="tools">
      <div class="search"><AppIcon name="search" />
        <input v-model="q" placeholder="搜索对外名或显示名" /></div>
    </div>
    <p v-if="loading" class="hint">加载中…</p>
    <EmptyState v-else-if="!filtered.length" icon="grid" title="还没有模型"
                desc="创建对外模型名，再绑定渠道即可对用户可见" />
    <section v-for="m in filtered" :key="m.id" class="card">
      <div class="top">
        <div class="id">
          <div class="name">{{ m.display_name }}
            <span v-if="m.is_default" class="def">默认</span>
            <span v-if="!m.enabled" class="off">已停用</span>
          </div>
          <div class="pn">{{ m.public_name }}</div>
        </div>
        <Switch :model-value="m.enabled" @update:model-value="(v: boolean) => toggleEnabled(m, v)" />
      </div>
      <div class="meta">
        <span class="pill">{{ m.tier }}</span>
        <span class="pill">{{ Math.round(m.context_limit / 1024) }}k 上下文</span>
        <span class="pill">输入 ¥{{ Number(m.price_input) }}/M</span>
        <span class="pill">输出 ¥{{ Number(m.price_output) }}/M</span>
      </div>
      <div class="acts">
        <button class="ghost" @click="openBind(m)"><AppIcon name="link" />绑定渠道</button>
        <button class="ghost" :disabled="m.is_default" @click="setDefault(m)">
          <AppIcon name="star" />设为默认</button>
        <button class="ghost" @click="openEdit(m)"><AppIcon name="pencil" />编辑</button>
        <button class="ghost danger" @click="del = m"><AppIcon name="trash" />删除</button>
      </div>
    </section>

    <Drawer :open="open" :title="editing ? '编辑模型' : '新建模型'"
            desc="对外名一旦创建不可修改，用户与历史统计都依赖它" @close="open = false">
      <label class="fl">对外模型名</label>
      <input v-model="form.public_name" class="fi" :disabled="!!editing" placeholder="例如：smart" />
      <label class="fl">显示名</label><input v-model="form.display_name" class="fi" placeholder="例如：主力模型" />
      <label class="fl">档位</label>
      <select v-model="form.tier" class="fi"><option value="fast">fast</option>
        <option value="standard">standard</option><option value="premium">premium</option></select>
      <div class="two">
        <div><label class="fl">上下文上限</label><input v-model.number="form.context_limit" class="fi" type="number" /></div>
        <div><label class="fl">最大输出</label><input v-model.number="form.max_output_tokens" class="fi" type="number" /></div>
      </div>
      <div class="two">
        <div><label class="fl">输入单价 ¥/M</label><input v-model.number="form.price_input" class="fi" type="number" step="0.01" /></div>
        <div><label class="fl">输出单价 ¥/M</label><input v-model.number="form.price_output" class="fi" type="number" step="0.01" /></div>
      </div>
      <template #footer><button class="primary" :disabled="busy" @click="save">保存</button></template>
    </Drawer>

    <Drawer :open="!!binding" title="绑定渠道"
            desc="填写该渠道上的真实模型名，对外名保持不变" @close="binding = null">
      <label class="fl">渠道</label>
      <select v-model="bindChannel" class="fi">
        <option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}（{{ c.type }}）</option>
      </select>
      <label class="fl">上游真实模型名</label>
      <input v-model="bindUpstream" class="fi" placeholder="例如：deepseek-chat" />
      <p class="note">可先在接口配置页「同步模型」拉取上游列表，再点击模型名快速绑定。</p>
      <template #footer><button class="primary" @click="doBind">确认绑定</button></template>
    </Drawer>

    <ConfirmDialog :open="!!del" title="删除模型" danger
                   message="删除后用户端不再可选。历史用量的模型名快照会保留，统计维度不丢失。"
                   :confirm-word="del?.public_name" @close="del = null" @confirm="doDelete" />
  </AdminLayout>
</template>

<style scoped>
.head { display: flex; align-items: flex-start; gap: 10px; padding: 14px 16px 10px; }
.head h1 { font-size: var(--fs-xl); font-weight: 700; }
.head p { font-size: var(--fs-cap); color: var(--t3); margin-top: 3px; }
.head > div { flex: 1; min-width: 0; }
.primary { width: 100%; padding: 12px 0; border: none; border-radius: var(--r-sm); background: var(--accent);
  color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.primary.sm { width: auto; padding: 8px 12px; font-size: var(--fs-cap); display: inline-flex; align-items: center; gap: 3px; }
.primary.sm .app-icon { width: 15px; height: 15px; }
.tools { padding: 0 16px; }
.search { position: relative; }
.search .app-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--t4); }
.search input { width: 100%; padding: 8px 10px 8px 32px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.hint { padding: 24px; text-align: center; color: var(--t4); }
.card { margin: 10px 16px 0; padding: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); }
.top { display: flex; align-items: center; gap: 8px; }
.id { flex: 1; min-width: 0; }
.name { font-size: var(--fs-md); font-weight: 700; display: flex; align-items: center; gap: 6px; }
.def { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--accent-soft); color: var(--accent); }
.off { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--fill); color: var(--t3); }
.pn { font-size: 10px; color: var(--t4); margin-top: 2px; }
.meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.pill { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: var(--surface-2); border: 1px solid var(--line); color: var(--t3); }
.acts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.ghost { display: inline-flex; align-items: center; gap: 3px; padding: 6px 9px; border: 1px solid var(--line-2);
  background: var(--surface); color: var(--t2); border-radius: var(--r-sm); font-size: var(--fs-cap); cursor: pointer; }
.ghost .app-icon { width: 14px; height: 14px; }
.ghost:disabled { opacity: .45; cursor: not-allowed; }
.ghost.danger:hover { border-color: var(--err); color: var(--err); }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 12px 0 4px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.fi:disabled { opacity: .6; }
.note { font-size: 10px; color: var(--t4); margin-top: 6px; line-height: 1.5; }
.two { display: flex; gap: 8px; }
.two > div { flex: 1; min-width: 0; }
</style>
