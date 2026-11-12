<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import AdminLayout from '../../admin/views/AdminLayout.vue'
import Drawer from '../../theme/components/Drawer.vue'
import EmptyState from '../../theme/components/EmptyState.vue'
import { computed, onMounted, ref } from 'vue'
import { experimentsApi, modelsApi, type ExperimentItem, type ExperimentReport } from '../../interfaces/api/resources'
import type { Model } from '../../interfaces/api/types'
import { ApiError } from '../../interfaces/api/client'
import { useToastStore } from '../../core/stores/toast'

const toast = useToastStore()
const items = ref<ExperimentItem[]>([])
const models = ref<Model[]>([])
const loading = ref(true)
const creating = ref(false)
const busy = ref(false)
const form = ref({ model_id: 0, channel_a: 0, channel_b: 0, ratio_a: 50 })
const reportFor = ref<ExperimentItem | null>(null)
const report = ref<ExperimentReport | null>(null)
const reportLoading = ref(false)

const boundChannels = computed(() =>
  models.value.find((m) => m.id === form.value.model_id)?.channels ?? [])

async function load() {
  loading.value = true
  try {
    const [exps, ms] = await Promise.all([experimentsApi.list(), modelsApi.list()])
    items.value = exps
    models.value = ms
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { loading.value = false }
}

function openCreate() {
  form.value = { model_id: 0, channel_a: 0, channel_b: 0, ratio_a: 50 }
  creating.value = true
}
function pickModel() {
  const chs = boundChannels.value
  form.value.channel_a = chs[0]?.channel_id ?? 0
  form.value.channel_b = chs[1]?.channel_id ?? 0
}
async function create() {
  if (!form.value.model_id || !form.value.channel_a || !form.value.channel_b) {
    toast.show('请选择模型与两个渠道', 'error'); return
  }
  if (form.value.channel_a === form.value.channel_b) {
    toast.show('A/B 必须是不同渠道', 'error'); return
  }
  busy.value = true
  try {
    await experimentsApi.create({ ...form.value })
    creating.value = false
    toast.show('实验已开始，流量按用户稳定分桶', 'success')
    await load()
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { busy.value = false }
}
async function openReport(e: ExperimentItem) {
  reportFor.value = e
  reportLoading.value = true
  report.value = null
  try { report.value = await experimentsApi.report(e.id) }
  catch (err) { toast.show((err as ApiError).message, 'error') }
  finally { reportLoading.value = false }
}
async function endExp(e: ExperimentItem) {
  try {
    await experimentsApi.end(e.id)
    toast.show('实验已结束，路由回退优先级/权重', 'success')
    reportFor.value = null
    await load()
  } catch (err) { toast.show((err as ApiError).message, 'error') }
}
function when(iso: string) { return new Date(iso).toLocaleDateString() }
onMounted(load)
</script>

<template>
  <AdminLayout>
    <div class="exps">
      <div class="head">
        <div>
          <h1>A/B 路由实验</h1>
          <p>同一模型绑两个渠道，按用户哈希稳定分桶，用真实流量对比成本/延迟/满意度。</p>
        </div>
        <button class="primary sm" @click="openCreate"><AppIcon name="split" />新建实验</button>
      </div>

      <p v-if="loading" class="hint">加载中…</p>
      <EmptyState v-else-if="!items.length" icon="split" title="还没有实验"
                  desc="选一个已绑定至少两个渠道的模型开始对比" />
      <article v-for="e in items" :key="e.id" class="exp-card">
        <div class="top">
          <span class="ric"><AppIcon name="split" /></span>
          <div class="id">
            <div class="name">{{ e.model_name }}</div>
            <div class="desc">{{ e.channel_a_name }} vs {{ e.channel_b_name }}</div>
          </div>
          <span class="badge" :class="e.status">{{ e.status === 'running' ? '进行中' : '已结束' }}</span>
        </div>
        <div class="ratio">
          <i :style="{ width: e.ratio_a + '%' }" />
          <span>A {{ e.ratio_a }}% / B {{ 100 - e.ratio_a }}%</span>
        </div>
        <div class="acts">
          <button class="ghost" @click="openReport(e)"><AppIcon name="pulse" />报告</button>
          <button v-if="e.status === 'running'" class="ghost danger" @click="endExp(e)">
            <AppIcon name="stop" />结束实验
          </button>
          <span class="since">{{ when(e.started_at) }} 开始</span>
        </div>
      </article>
    </div>

    <Drawer :open="creating" title="新建实验" desc="实验期间该模型的流量按分桶走指定渠道"
            @close="creating = false">
      <label class="fl">1. 选择模型</label>
      <select v-model="form.model_id" class="fi model-sel" @change="pickModel">
        <option :value="0" disabled>请选择模型</option>
        <option v-for="m in models" :key="m.id" :value="m.id">
          {{ m.display_name }}（{{ m.channels?.length ?? 0 }} 个渠道）
        </option>
      </select>
      <label class="fl">2. 选择 A/B 渠道</label>
      <div class="two">
        <select v-model="form.channel_a" class="fi ch-a">
          <option :value="0" disabled>渠道 A</option>
          <option v-for="c in boundChannels" :key="c.channel_id" :value="c.channel_id">
            {{ c.channel_name }}
          </option>
        </select>
        <select v-model="form.channel_b" class="fi ch-b">
          <option :value="0" disabled>渠道 B</option>
          <option v-for="c in boundChannels" :key="c.channel_id" :value="c.channel_id">
            {{ c.channel_name }}
          </option>
        </select>
      </div>
      <label class="fl">3. A 桶流量比例：{{ form.ratio_a }}%</label>
      <input v-model.number="form.ratio_a" type="range" min="1" max="99" class="range" />
      <p class="tip">同一用户始终进同一桶；渠道被禁用时自动回退常规选路。</p>
      <template #footer>
        <button class="primary" :disabled="busy" @click="create">
          {{ busy ? '创建中…' : '创建实验' }}
        </button>
      </template>
    </Drawer>

    <Drawer :open="!!reportFor" :title="`实验报告 · ${reportFor?.model_name ?? ''}`"
            desc="按分桶聚合真实调用的延迟、成本与满意度" @close="reportFor = null">
      <p v-if="reportLoading" class="hint">加载中…</p>
      <template v-else-if="report">
        <div v-for="b in report.buckets" :key="b.bucket" class="bucket-row">
          <div class="bhead">
            <b>{{ b.bucket.toUpperCase }} · {{ b.channel_name }}</b>
            <span class="bcalls">{{ b.calls }} 次调用</span>
          </div>
          <div class="bgrid">
            <span>平均延迟<b>{{ b.avg_total_ms }}ms</b></span>
            <span>P95<b>{{ b.p95_total_ms === null ? '—' : b.p95_total_ms + 'ms' }}</b></span>
            <span>总成本<b>¥{{ b.cost.toFixed(4) }}</b></span>
            <span>好评 / 差评<b>{{ b.up }} / {{ b.down }}</b></span>
          </div>
        </div>
        <p class="recommend"><AppIcon name="sparkles" />{{ report.recommendation }}</p>
        <button v-if="reportFor?.status === 'running'" class="primary danger-btn"
                @click="reportFor && endExp(reportFor)">结束实验并回退权重路由</button>
      </template>
    </Drawer>
  </AdminLayout>
</template>

<style scoped>
.exps { padding-bottom: 24px; }
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
.danger-btn { background: var(--err); margin-top: 10px; }
.hint { padding: 24px; text-align: center; color: var(--t4); }
.exp-card { margin: 10px 16px 0; padding: 12px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-md); }
.top { display: flex; align-items: center; gap: 9px; }
.ric { width: 36px; height: 36px; border-radius: var(--r-md); background: var(--accent-soft);
  color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ric .app-icon { width: 20px; height: 20px; }
.id { flex: 1; min-width: 0; }
.name { font-size: var(--fs-lg); font-weight: 700; }
.desc { font-size: var(--fs-cap); color: var(--t3); margin-top: 2px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; background: var(--surface-2); color: var(--t3); }
.badge.running { background: var(--accent-soft); color: var(--accent); }
.ratio { position: relative; height: 18px; border-radius: 9px; background: var(--surface-2);
  margin: 10px 0 8px; overflow: hidden; }
.ratio i { position: absolute; inset: 0 auto 0 0; background: var(--accent); opacity: .35; }
.ratio span { position: relative; display: block; text-align: center; font-size: 10px;
  line-height: 18px; color: var(--t2); }
.acts { display: flex; gap: 8px; align-items: center; }
.ghost { display: inline-flex; align-items: center; gap: 4px; padding: 6px 10px;
  border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--surface);
  color: var(--t2); font-size: var(--fs-cap); cursor: pointer; }
.ghost .app-icon { width: 14px; height: 14px; }
.ghost.danger { color: var(--err); border-color: var(--err); }
.since { margin-left: auto; font-size: 10px; color: var(--t4); }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 12px 0 6px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.range { width: 100%; accent-color: var(--accent); }
.tip { font-size: var(--fs-cap); color: var(--t4); margin-top: 6px; line-height: 1.5; }
.bucket-row { border: 1px solid var(--line); border-radius: var(--r-md); padding: 10px 12px; margin-bottom: 8px; }
.bhead { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.bhead b { font-size: var(--fs-md); }
.bcalls { font-size: var(--fs-cap); color: var(--t3); }
.bgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px; }
.bgrid span { font-size: var(--fs-cap); color: var(--t3); display: flex; justify-content: space-between; }
.bgrid b { color: var(--t1); font-weight: 600; }
.recommend { display: flex; gap: 6px; align-items: flex-start; padding: 10px 12px;
  background: var(--accent-soft); border-radius: var(--r-md); font-size: var(--fs-sm);
  color: var(--t2); line-height: 1.6; margin-top: 4px; }
.recommend .app-icon { width: 16px; height: 16px; color: var(--accent); flex-shrink: 0; margin-top: 2px; }
@media (min-width: 1024px) {
  .head, .exp-card { margin-left: 24px; margin-right: 24px; }
}
</style>