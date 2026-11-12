<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import AdminLayout from '../../admin/views/AdminLayout.vue'
import Drawer from '../../theme/components/Drawer.vue'
import Switch from '../../theme/components/Switch.vue'
import Chip from '../../theme/components/Chip.vue'
import ConfirmDialog from '../../theme/components/ConfirmDialog.vue'
import EmptyState from '../../theme/components/EmptyState.vue'
import Sparkline from '../../stats/components/Sparkline.vue'
import { alertsApi, channelsApi, modelsApi, settingsApi } from '../../interfaces/api/resources'
import type { Channel, Preset } from '../../interfaces/api/types'
import { ApiError } from '../../interfaces/api/client'
import { useToastStore } from '../../core/stores/toast'

const toast = useToastStore()
const rows = ref<Channel[]>([])
const presets = ref<Record<string, Preset[]>>({})
const loading = ref(true)
const q = ref('')
const statusFilter = ref('all')
const sortBy = ref<'priority' | 'name' | 'latency'>('priority')
const editing = ref<Channel | null>(null)
const open = ref(false)
const busy = ref(false)
const testing = ref<number | null>(null)
const testResult = ref<Record<number, string>>({})
const syncing = ref<number | null>(null)
const discovered = ref<Record<number, string[]>>({})
const confirmDel = ref<Channel | null>(null)
const impact = ref<{ channel: Channel; models: string[] } | null>(null)
const reenable = ref<Channel | null>(null)
const healthFor = ref<Channel | null>(null)
const healthData = ref<{ samples: { sampled_at: string; latency_ms: number | null; success: boolean; error_code: string | null }[]; fail_rate: number | null } | null>(null)
const healthLoading = ref(false)
const alertForm = reactive({ url: '', type: 'dingtalk', enabled: true })
const alertVersion = ref(0)
const alertBusy = ref(false)

const latencies = computed(() =>
  (healthData.value?.samples ?? [])
    .filter((x) => x.latency_ms !== null)
    .map((x) => x.latency_ms as number)
    .reverse())

async function openHealth(c: Channel) {
  healthFor.value = c
  healthLoading.value = true
  healthData.value = null
  try { healthData.value = await channelsApi.health(c.id) }
  catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { healthLoading.value = false }
  try {
    const list = await settingsApi.list()
    const cfg = list.find((x) => x.key === 'alert_webhook')
    if (cfg) {
      const v = cfg.value as { url?: string; type?: string; enabled?: boolean }
      alertForm.url = v.url ?? ''
      alertForm.type = v.type ?? 'dingtalk'
      alertForm.enabled = v.enabled ?? true
      alertVersion.value = cfg.version
    }
  } catch { /* 配置可选 */ }
}
async function saveAlert() {
  alertBusy.value = true
  try {
    await settingsApi.put('alert_webhook', { ...alertForm }, alertVersion.value)
    alertVersion.value += 1
    toast.show('告警配置已保存', 'success')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { alertBusy.value = false }
}
async function testAlert() {
  try { await alertsApi.test(); toast.show('测试消息已发送，请到群里确认', 'success') }
  catch (e) { toast.show((e as ApiError).message, 'error') }
}
function fmtTime(iso: string) { return new Date(iso).toLocaleTimeString().slice(0, 5) }

const PROTOCOLS = [
  { key: 'openai_compatible', label: 'OpenAI 兼容', hint: '覆盖面最广：OpenAI / DeepSeek / 百炼 / OpenRouter / Groq / Ollama 等' },
  { key: 'anthropic', label: 'Anthropic', hint: 'Messages 协议，system 在顶层，max_tokens 必填' },
  { key: 'gemini', label: 'Gemini', hint: 'generateContent 协议，Key 走请求头，角色名为 model' },
]
const ALL_PARAMS = ['temperature', 'top_p', 'max_tokens', 'stream', 'stop',
                    'stop_sequences', 'topP', 'maxOutputTokens', 'stopSequences']

const form = reactive({
  name: '', type: 'openai_compatible', base_url: '', api_key: '', preset: '',
  weight: 100, priority: 0, supported_params: [] as string[],
})

const filtered = computed(() => {
  let out = rows.value.filter((c) => {
    const okQ = !q.value.trim() || c.name.toLowerCase().includes(q.value.trim().toLowerCase())
      || c.base_url.toLowerCase().includes(q.value.trim().toLowerCase())
    const okS = statusFilter.value === 'all' || c.status === statusFilter.value
    return okQ && okS
  })
  out = [...out].sort((a, b) => {
    if (sortBy.value === 'name') return a.name.localeCompare(b.name)
    if (sortBy.value === 'latency') return (a.last_latency_ms ?? 9e9) - (b.last_latency_ms ?? 9e9)
    return b.priority - a.priority || b.weight - a.weight
  })
  return out
})
const enabledCount = computed(() => rows.value.filter((c) => c.status === 'enabled').length)
const currentPreset = computed(() => presets.value[form.type] ?? [])

async function load() {
  loading.value = true
  try {
    const [cs, ps] = await Promise.all([channelsApi.list(), channelsApi.presets()])
    rows.value = cs
    presets.value = ps
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { loading.value = false }
}
function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', type: 'openai_compatible', base_url: '', api_key: '',
    preset: '', weight: 100, priority: 0,
    supported_params: [...(presets.value.openai_compatible?.[0]?.supported_params ?? [])] })
  open.value = true
}
function openEdit(c: Channel) {
  editing.value = c
  Object.assign(form, { name: c.name, type: c.type, base_url: c.base_url, api_key: '',
    preset: c.preset ?? '', weight: c.weight, priority: c.priority,
    supported_params: [...(c.supported_params ?? [])] })
  open.value = true
}
function onProtocolChange() {
  form.preset = ''
  form.supported_params = [...(presets.value[form.type]?.[0]?.supported_params ?? [])]
}
function applyPreset(name: string) {
  const p = currentPreset.value.find((x) => x.name === name)
  if (!p) return
  form.preset = name
  form.base_url = p.base_url
  form.supported_params = [...p.supported_params]
  if (!form.name) form.name = name
}
function toggleParam(p: string) {
  const i = form.supported_params.indexOf(p)
  if (i >= 0) form.supported_params.splice(i, 1)
  else form.supported_params.push(p)
}
async function save() {
  if (!form.name.trim() || !form.base_url.trim()) { toast.show('名称与 Base URL 必填', 'error'); return }
  if (!editing.value && !form.api_key.trim()) { toast.show('新建渠道必须填写 API Key', 'error'); return }
  busy.value = true
  try {
    if (editing.value) {
      const body: Record<string, unknown> = {
        version: editing.value.version, name: form.name, base_url: form.base_url,
        weight: form.weight, priority: form.priority, supported_params: form.supported_params,
      }
      if (form.api_key.trim()) body.api_key = form.api_key
      const updated = await channelsApi.patch(editing.value.id, body)
      rows.value = rows.value.map((c) => (c.id === updated.id ? updated : c))
      toast.show('渠道已更新', 'success')
    } else {
      const created = await channelsApi.create({ ...form, preset: form.preset || null })
      rows.value.unshift(created)
      toast.show('渠道已创建，建议先测试连通性', 'success')
    }
    open.value = false
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { busy.value = false }
}
async function runTest(c: Channel) {
  testing.value = c.id
  try {
    const r = await channelsApi.test(c.id)
    testResult.value[c.id] = r.ok ? `连通正常 · ${r.latency_ms}ms` : `失败：${r.error_kind} ${r.message}`
    c.last_latency_ms = r.latency_ms
    toast.show(r.ok ? `连通正常，延迟 ${r.latency_ms}ms` : `测试失败：${r.error_kind}`, r.ok ? 'success' : 'error')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { testing.value = null }
}
async function runSync(c: Channel) {
  syncing.value = c.id
  try {
    const r = await channelsApi.sync(c.id)
    discovered.value[c.id] = r.models
    toast.show(r.models.length ? `拉取到 ${r.models.length} 个模型` : '上游返回空模型列表',
      r.models.length ? 'success' : 'info')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { syncing.value = null }
}
async function bindDiscovered(c: Channel, upstream: string) {
  const ms = await modelsApi.list()
  if (!ms.length) { toast.show('请先在模型注册表创建一个对外模型', 'error'); return }
  try {
    await modelsApi.bind(ms[0].id, c.id, upstream)
    toast.show(`已把 ${upstream} 绑定到 ${ms[0].public_name}`, 'success')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
}
async function onToggle(c: Channel, next: boolean) {
  if (next && c.status === 'auto_disabled') { reenable.value = c; return }
  try {
    const r = await channelsApi.toggle(c.id, next)
    c.status = r.status as Channel['status']
    if (r.affected_models.length) {
      toast.show(`已停用，联动停用模型：${r.affected_models.join('、')}`, 'info', 4200)
    } else toast.show(next ? '渠道已启用' : '渠道已停用', 'success')
  } catch (e) { toast.show((e as ApiError).message, 'error'); await load() }
}
async function confirmReenable() {
  const c = reenable.value
  if (!c) return
  try {
    await channelsApi.toggle(c.id, true, true)
    c.status = 'enabled'; c.fail_count = 0
    toast.show('已恢复启用并清零失败计数', 'success')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  reenable.value = null
}
async function askDelete(c: Channel) {
  try { await channelsApi.remove(c.id, false); confirmDel.value = c }
  catch (e) {
    const err = e as ApiError
    if (err.status === 409 && err.detail?.affected_models) {
      impact.value = { channel: c, models: err.detail.affected_models as string[] }
    } else toast.show(err.message, 'error')
  }
}
async function doDelete(c: Channel) {
  try {
    await channelsApi.remove(c.id, true)
    rows.value = rows.value.filter((x) => x.id !== c.id)
    toast.show('渠道已删除', 'success')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  confirmDel.value = null
  impact.value = null
}
function statusText(s: string) {
  return s === 'enabled' ? '启用中' : s === 'auto_disabled' ? '自动禁用' : '已停用'
}
onMounted(load)
</script>

<template>
  <AdminLayout>
    <header class="head">
      <div>
        <h1>模型接口配置</h1>
        <p>按协议接入，填对应类型端点即可通用 · 密钥仅存服务端，界面只回显末 4 位</p>
      </div>
      <button class="primary sm" @click="openCreate">
        <AppIcon name="plus" />添加接口
      </button>
    </header>

    <div class="stats">
      <div class="stat"><b>{{ rows.length }}</b><span>渠道总数</span></div>
      <div class="stat"><b>{{ enabledCount }}</b><span>启用中</span></div>
      <div class="stat"><b>{{ rows.filter(r => r.status === 'auto_disabled').length }}</b><span>自动禁用</span></div>
    </div>

    <div class="tools">
      <div class="search">
        <AppIcon name="search" />
        <input v-model="q" placeholder="搜索名称或 Base URL" />
      </div>
      <div class="chips">
        <Chip :active="statusFilter === 'all'" @click="statusFilter = 'all'">全部</Chip>
        <Chip :active="statusFilter === 'enabled'" @click="statusFilter = 'enabled'">启用中</Chip>
        <Chip :active="statusFilter === 'disabled'" @click="statusFilter = 'disabled'">已停用</Chip>
        <Chip :active="statusFilter === 'auto_disabled'" @click="statusFilter = 'auto_disabled'">自动禁用</Chip>
        <Chip icon="sort" @click="sortBy = sortBy === 'priority' ? 'name' : sortBy === 'name' ? 'latency' : 'priority'">
          {{ sortBy === 'priority' ? '按优先级' : sortBy === 'name' ? '按名称' : '按延迟' }}
        </Chip>
      </div>
    </div>

    <p v-if="loading" class="hint">加载中…</p>
    <EmptyState v-else-if="!filtered.length" icon="cloud-off" title="没有匹配的渠道"
                desc="换个筛选条件，或添加一个新的模型接口" />

    <section v-for="c in filtered" :key="c.id" class="card">
      <div class="top">
        <span class="logo" :class="c.type"><AppIcon :name="c.type === 'anthropic' ? 'brain' : c.type === 'gemini' ? 'sparkles' : 'bolt'" /></span>
        <div class="id">
          <div class="name">{{ c.name }}</div>
          <div class="url">{{ c.base_url }}</div>
        </div>
        <span class="tag" :class="c.status">{{ statusText(c.status) }}</span>
      </div>

      <div class="meta">
        <span class="pill">{{ PROTOCOLS.find(p => p.key === c.type)?.label ?? c.type }}</span>
        <span class="pill">Key {{ c.api_key_hint }}</span>
        <span class="pill">优先级 {{ c.priority }}</span>
        <span class="pill">权重 {{ c.weight }}</span>
        <span v-if="c.last_latency_ms !== null" class="pill">{{ c.last_latency_ms }}ms</span>
        <span v-if="c.fail_count" class="pill warn">失败 {{ c.fail_count }} 次</span>
      </div>

      <p v-if="testResult[c.id]" class="result">{{ testResult[c.id] }}</p>

      <div v-if="discovered[c.id]?.length" class="disc">
        <span class="dl">上游模型（点击绑定到首个对外模型）</span>
        <div class="dchips">
          <button v-for="m in discovered[c.id]" :key="m" class="dchip" @click="bindDiscovered(c, m)">{{ m }}</button>
        </div>
      </div>

      <div class="acts">
        <button class="ghost" :disabled="testing === c.id" @click="runTest(c)">
          <AppIcon name="signal-check" />{{ testing === c.id ? '测试中…' : '测试连通' }}
        </button>
        <button class="ghost" @click="openHealth(c)"><AppIcon name="pulse" />健康</button>
        <button class="ghost" :disabled="syncing === c.id" @click="runSync(c)">
          <AppIcon name="refresh" />{{ syncing === c.id ? '拉取中…' : '同步模型' }}
        </button>
        <button class="ghost" @click="openEdit(c)"><AppIcon name="pencil" />编辑</button>
        <button class="ghost danger" @click="askDelete(c)"><AppIcon name="trash" />删除</button>
        <Switch :model-value="c.status === 'enabled'" @update:model-value="(v: boolean) => onToggle(c, v)" />
      </div>
    </section>

    <Drawer :open="open" :title="editing ? '编辑渠道' : '添加接口'"
            desc="先选协议类型，表单只显示该协议需要的字段" @close="open = false">
      <label class="fl">协议类型</label>
      <div class="protos">
        <button v-for="p in PROTOCOLS" :key="p.key" class="proto"
                :class="{ on: form.type === p.key }" :disabled="!!editing"
                @click="form.type = p.key; onProtocolChange()">
          <b>{{ p.label }}</b><small>{{ p.hint }}</small>
        </button>
      </div>

      <label class="fl">厂商预设（一键填充）</label>
      <select class="fi" :value="form.preset" @change="applyPreset(($event.target as HTMLSelectElement).value)">
        <option value="">不使用预设，手动填写</option>
        <option v-for="p in currentPreset" :key="p.name" :value="p.name">{{ p.name }}</option>
      </select>

      <label class="fl">渠道名称</label>
      <input v-model="form.name" class="fi" placeholder="例如：DeepSeek 主账号" />
      <label class="fl">Base URL</label>
      <input v-model="form.base_url" class="fi" placeholder="https://api.deepseek.com/v1" />
      <label class="fl">API Key {{ editing ? '（留空表示不修改）' : '' }}</label>
      <input v-model="form.api_key" class="fi" type="password"
             :placeholder="editing ? `当前 ${editing.api_key_hint}` : 'sk-...'" />
      <p class="note">密钥加密后只存服务端，任何接口都不会返回明文。</p>

      <template v-if="form.type === 'anthropic'">
        <label class="fl">anthropic-version</label>
        <input class="fi" value="2023-06-01" disabled />
      </template>
      <p v-if="form.type === 'gemini'" class="note">Gemini 的 Key 通过 x-goog-api-key 请求头传递，不会出现在 URL 中。</p>

      <label class="fl">参数白名单（不支持的参数不会发给上游）</label>
      <div class="params">
        <button v-for="p in ALL_PARAMS" :key="p" class="param"
                :class="{ on: form.supported_params.includes(p) }" @click="toggleParam(p)">{{ p }}</button>
      </div>

      <div class="two">
        <div><label class="fl">优先级</label><input v-model.number="form.priority" class="fi" type="number" /></div>
        <div><label class="fl">权重</label><input v-model.number="form.weight" class="fi" type="number" /></div>
      </div>
      <template #footer>
        <button class="primary" :disabled="busy" @click="save">{{ busy ? '保存中…' : '保存' }}</button>
      </template>
    </Drawer>

    <ConfirmDialog :open="!!confirmDel" title="删除渠道" danger
                   :message="`删除后该渠道的密钥与配置将不可恢复。`"
                   :confirm-word="confirmDel?.name" @close="confirmDel = null"
                   @confirm="confirmDel && doDelete(confirmDel)" />
    <ConfirmDialog :open="!!impact" title="该渠道仍被模型绑定" danger
                   :message="`删除后这些模型将失去该渠道：${impact?.models.join('、')}。若它是唯一渠道，模型会随之不可用。`"
                   :confirm-word="impact?.channel.name" @close="impact = null"
                   @confirm="impact && doDelete(impact.channel)" />
    <ConfirmDialog :open="!!reenable" title="恢复自动禁用的渠道"
                   message="该渠道曾因连续失败或鉴权问题被自动禁用。确认已排除故障后再恢复，失败计数将清零。"
                   @close="reenable = null" @confirm="confirmReenable" />

    <Drawer :open="!!healthFor" :title="`渠道健康 · ${healthFor?.name ?? ''}`"
            desc="每分钟探测采样，保留 7 天；告警 10 分钟去重" @close="healthFor = null">
      <p v-if="healthLoading" class="hint">加载中…</p>
      <template v-else-if="healthData">
        <div class="hstats">
          <div class="stat"><b>{{ healthData.samples.length }}</b><span>近 24h 采样</span></div>
          <div class="stat"><b>{{ healthData.fail_rate === null ? '—' : Math.round(healthData.fail_rate * 100) + '%' }}</b><span>近 10min 失败率</span></div>
        </div>
        <p class="hlabel">延迟曲线（ms）</p>
        <Sparkline :values="latencies" :height="56" />
        <p v-if="!latencies.length" class="hint">暂无采样，调度器每分钟探测一次。</p>
        <div v-for="(x, i) in healthData.samples.slice(0, 8)" :key="i" class="hrow">
          <span class="htime">{{ fmtTime(x.sampled_at) }}</span>
          <span class="hok" :class="{ bad: !x.success }">{{ x.success ? '成功' : (x.error_code ?? '失败') }}</span>
          <span class="hlat">{{ x.latency_ms === null ? '—' : x.latency_ms + 'ms' }}</span>
        </div>
      </template>
      <label class="fl">告警 Webhook（渠道熔断或失败率 &gt; 50% 时推送）</label>
      <input v-model="alertForm.url" class="fi" placeholder="https://oapi.dingtalk.com/robot/send?access_token=…" />
      <div class="alert-row">
        <select v-model="alertForm.type" class="fi">
          <option value="dingtalk">钉钉</option>
          <option value="feishu">飞书</option>
          <option value="generic">通用 JSON</option>
        </select>
        <label class="en"><input v-model="alertForm.enabled" type="checkbox" />启用</label>
      </div>
      <div class="alert-row">
        <button class="primary sm" :disabled="alertBusy || !alertForm.url" @click="saveAlert">保存配置</button>
        <button class="ghost" :disabled="!alertForm.url" @click="testAlert">
          <AppIcon name="send" />测试发送
        </button>
      </div>
    </Drawer>
  </AdminLayout>
</template>

<style scoped>
.head { display: flex; align-items: flex-start; gap: 10px; padding: 14px 16px 10px; }
.head h1 { font-size: var(--fs-xl); font-weight: 700; }
.head p { font-size: var(--fs-cap); color: var(--t3); margin-top: 3px; line-height: 1.5; }
.head > div { flex: 1; min-width: 0; }
.primary { width: 100%; padding: 12px 0; border: none; border-radius: var(--r-sm); background: var(--accent);
  color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .5; }
.primary.sm { width: auto; padding: 8px 12px; font-size: var(--fs-cap); display: inline-flex;
  align-items: center; gap: 3px; flex-shrink: 0; }
.primary.sm .app-icon { width: 15px; height: 15px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 0 16px; }
.stat { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md);
  padding: 10px; text-align: center; }
.stat b { display: block; font-size: 20px; font-weight: 800; }
.stat span { font-size: 10px; color: var(--t3); }
.tools { padding: 10px 16px 0; }
.search { position: relative; }
.search .app-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  font-size: 16px; color: var(--t4); }
.search input { width: 100%; padding: 8px 10px 8px 32px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.chips { display: flex; gap: 6px; overflow-x: auto; padding: 8px 0 2px; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.hint { padding: 24px; text-align: center; color: var(--t4); }
.hstats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
.hlabel { font-size: var(--fs-cap); color: var(--t3); margin: 8px 0 4px; }
.hrow { display: flex; gap: 10px; align-items: center; padding: 6px 8px; border-bottom: 1px solid var(--line);
  font-size: var(--fs-cap); }
.htime { color: var(--t4); width: 44px; }
.hok { flex: 1; color: var(--ok, #22c55e); }
.hok.bad { color: var(--err); }
.hlat { color: var(--t3); }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 14px 0 6px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.alert-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
.alert-row .fi { flex: 1; }
.en { display: inline-flex; gap: 5px; align-items: center; font-size: var(--fs-cap); color: var(--t2); flex-shrink: 0; }
.card { margin: 10px 16px 0; padding: 12px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-md); box-shadow: var(--shadow); }
.top { display: flex; align-items: center; gap: 9px; }
.logo { width: 30px; height: 30px; border-radius: 8px; background: var(--t1); color: var(--accent);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.logo .app-icon { width: 17px; height: 17px; }
.id { flex: 1; min-width: 0; }
.name { font-size: var(--fs-md); font-weight: 700; }
.url { font-size: 10px; color: var(--t4); word-break: break-all; margin-top: 1px; }
.tag { font-size: 10px; padding: 2px 7px; border-radius: 3px; font-weight: 700; flex-shrink: 0; }
.tag.enabled { background: var(--ok-soft); color: var(--ok); }
.tag.disabled { background: var(--fill); color: var(--t3); }
.tag.auto_disabled { background: var(--err-soft); color: var(--err); }
.meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.pill { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: var(--surface-2);
  border: 1px solid var(--line); color: var(--t3); }
.pill.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn-line); }
.result { margin-top: 8px; font-size: var(--fs-cap); color: var(--t2); background: var(--surface-2);
  padding: 6px 8px; border-radius: var(--r-sm); }
.disc { margin-top: 8px; }
.dl { font-size: 10px; color: var(--t4); }
.dchips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.dchip { font-size: 10px; padding: 3px 7px; border-radius: 4px; border: 1px dashed var(--line-2);
  background: var(--surface); color: var(--accent); cursor: pointer; }
.acts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.ghost { display: inline-flex; align-items: center; gap: 3px; padding: 6px 9px; border: 1px solid var(--line-2);
  background: var(--surface); color: var(--t2); border-radius: var(--r-sm); font-size: var(--fs-cap); cursor: pointer; }
.ghost .app-icon { width: 14px; height: 14px; }
.ghost:disabled { opacity: .5; cursor: not-allowed; }
.ghost.danger:hover { border-color: var(--err); color: var(--err); }
.acts > :last-child { margin-left: auto; }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 12px 0 4px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.fi:disabled { opacity: .6; }
.note { font-size: 10px; color: var(--t4); margin-top: 5px; line-height: 1.5; }
.protos { display: flex; flex-direction: column; gap: 6px; }
.proto { text-align: left; padding: 9px 10px; border: 1px solid var(--line); border-radius: var(--r-sm);
  background: var(--surface); cursor: pointer; }
.proto.on { border-color: var(--accent); background: var(--accent-soft); }
.proto:disabled { opacity: .7; cursor: not-allowed; }
.proto b { display: block; font-size: var(--fs-md); }
.proto small { display: block; font-size: 10px; color: var(--t3); margin-top: 2px; line-height: 1.45; }
.params { display: flex; flex-wrap: wrap; gap: 5px; }
.param { font-size: 10px; padding: 4px 8px; border-radius: 4px; border: 1px solid var(--line);
  background: var(--surface-2); color: var(--t3); cursor: pointer; }
.param.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 600; }
.two { display: flex; gap: 8px; }
.two > div { flex: 1; min-width: 0; }
@media (min-width: 1024px) {
  .head, .stats, .tools, .card { margin-left: 24px; margin-right: 24px; }
  .head { padding-left: 0; padding-right: 0; }
  .stats { padding: 0; grid-template-columns: repeat(3, 200px); }
  .tools { padding-left: 0; padding-right: 0; }
  .card { margin-left: 24px; margin-right: 24px; }
}
</style>
