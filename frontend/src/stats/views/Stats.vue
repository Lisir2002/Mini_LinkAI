<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import Sparkline from '../components/Sparkline.vue'
import AdminLayout from '../../admin/views/AdminLayout.vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { statsApi, type StatsDailyItem } from '../../interfaces/api/resources'
import { streamGetSSE } from '../../interfaces/api/sse'
import type { FeedbackStats, LiveTick } from '../../interfaces/api/types'
import { useToastStore } from '../../core/stores/toast'

const toast = useToastStore()
const tab = ref<'feedback' | 'live'>('feedback')
const fb = ref<FeedbackStats | null>(null)
const trend = ref<StatsDailyItem[]>([])
const recomputing = ref(false)

async function loadTrend() {
  try { trend.value = (await statsApi.overview(14)).items } catch { trend.value = [] }
}
async function recompute() {
  recomputing.value = true
  try {
    await statsApi.recompute()
    await loadTrend()
    toast.show('预聚合已刷新', 'success')
  } catch (e: any) { toast.show(e.message ?? '刷新失败', 'error') }
  finally { recomputing.value = false }
}
const callsTrend = computed(() => trend.value.map((x) => x.ai_calls))
const costTrend = computed(() => trend.value.map((x) => Number(x.cost)))
const fbLoading = ref(true)
const tick = ref<LiveTick | null>(null)
const callsHist = ref<number[]>([])
const costHist = ref<number[]>([])
const connected = ref(false)
let abort: AbortController | null = null
let retryTimer: number | undefined
let retry = 1000
let stopped = false

async function loadFeedback() {
  fbLoading.value = true
  try { fb.value = await statsApi.feedback() }
  catch (e: any) { toast.show(e.message ?? '统计加载失败', 'error') }
  finally { fbLoading.value = false }
}

function applyTick(t: LiveTick) {
  tick.value = t
  connected.value = true
  callsHist.value = [...callsHist.value.slice(-29), t.calls_per_min]
  costHist.value = [...costHist.value.slice(-29), t.budget.monthly_cost]
}

async function connect() {
  if (stopped || tab.value !== 'live') return
  abort?.abort()
  abort = new AbortController()
  try {
    await streamGetSSE('/api/admin/stats/live?interval=5', (e) => {
      if (e.event === 'tick') { retry = 1000; applyTick(e.data as unknown as LiveTick) }
    }, abort.signal)
  } catch { /* 网络中断或主动取消 */ }
  connected.value = false
  if (!stopped && tab.value === 'live' && !document.hidden) {
    retryTimer = window.setTimeout(() => void connect(), retry)
    retry = Math.min(retry * 2, 30000)
  }
}

function switchTab(t: 'feedback' | 'live') {
  tab.value = t
  if (t === 'live') { retry = 1000; void connect() }
  else { abort?.abort(); window.clearTimeout(retryTimer); connected.value = false }
}

function onVis() {
  if (document.hidden) { abort?.abort(); window.clearTimeout(retryTimer) }
  else if (tab.value === 'live') { retry = 1000; void connect() }
}

function pct(n: number, d: number) { return d > 0 ? Math.min(100, (n / d) * 100) : 0 }
function rate(r: number | null) { return r === null ? '—' : `${Math.round(r * 100)}%` }
function statusText(s: string) {
  return s === 'enabled' ? '正常' : s === 'auto_disabled' ? '熔断' : '停用'
}

onMounted(() => { void loadFeedback(); void loadTrend(); document.addEventListener('visibilitychange', onVis) })
onUnmounted(() => {
  stopped = true
  abort?.abort()
  window.clearTimeout(retryTimer)
  document.removeEventListener('visibilitychange', onVis)
})
</script>

<template>
  <AdminLayout>
    <div class="stats">
      <h1 class="page-title">数据统计</h1>
      <div class="tabs">
        <button :class="{ on: tab === 'feedback' }" @click="switchTab('feedback')">
          <AppIcon name="thumbs-up" />满意度
        </button>
        <button :class="{ on: tab === 'live' }" @click="switchTab('live')">
          <AppIcon name="pulse" />实时
          <i class="dot" :class="{ live: connected }" />
        </button>
      </div>

      <section v-if="tab === 'feedback'">
        <p v-if="fbLoading" class="hint">加载中…</p>
        <template v-else-if="fb">
          <div class="cards">
            <div class="card"><b>{{ fb.total.up }}</b><span>有帮助</span></div>
            <div class="card"><b>{{ fb.total.down }}</b><span>没帮助</span></div>
            <div class="card accent"><b>{{ rate(fb.total.rate) }}</b><span>好评率</span></div>
          </div>
          <h2 class="sec">按模型</h2>
          <p v-if="!fb.by_model.length" class="hint">还没有带评价的模型回复。</p>
          <div v-for="m in fb.by_model" :key="m.id" class="frow">
            <span class="fname">{{ m.display_name }}</span>
            <div class="fbar">
              <i class="up" :style="{ width: pct(m.up, m.up + m.down) + '%' }" />
            </div>
            <span class="fnum">{{ m.up }} / {{ m.up + m.down }}</span>
          </div>
          <div class="trend">
            <div class="trend-head">
              <h2 class="sec">用量趋势（近 14 天预聚合）</h2>
              <button class="mini-btn" :disabled="recomputing" @click="recompute">
                <AppIcon name="refresh" />{{ recomputing ? '刷新中…' : '刷新预聚合' }}
              </button>
            </div>
            <p v-if="!trend.length" class="hint">暂无预聚合数据，点「刷新预聚合」生成。</p>
            <div v-else class="charts">
              <div class="chart"><p class="ct">每日 AI 调用</p><Sparkline :values="callsTrend" /></div>
              <div class="chart"><p class="ct">每日成本（元）</p><Sparkline :values="costTrend" /></div>
            </div>
          </div>
          <h2 class="sec">差评房间 TOP5</h2>
          <p v-if="!fb.top_rooms.length" class="hint">暂无房间差评。</p>
          <div v-for="r in fb.top_rooms" :key="r.id" class="frow">
            <span class="fname">{{ r.name }}</span>
            <span class="fnum down">{{ r.down }} 差评 · {{ r.up }} 好评</span>
          </div>
        </template>
      </section>

      <section v-else>
        <div class="cards">
          <div class="card"><b>{{ tick?.online ?? '—' }}</b><span>在线成员（5 分钟活跃）</span></div>
          <div class="card"><b>{{ tick?.calls_per_min ?? '—' }}</b><span>本分钟 AI 调用</span></div>
          <div class="card accent">
            <b>¥{{ (tick?.budget.monthly_cost ?? 0).toFixed(2) }}</b>
            <span>本月成本 / 预算 ¥{{ tick?.budget.monthly_budget ?? '—' }}</span>
          </div>
        </div>
        <div class="budget">
          <i :style="{ width: pct(tick?.budget.monthly_cost ?? 0, tick?.budget.monthly_budget ?? 0) + '%' }" />
        </div>
        <div class="charts">
          <div class="chart">
            <p class="ct">调用速率（近 30 次推送）</p>
            <Sparkline :values="callsHist" />
          </div>
          <div class="chart">
            <p class="ct">月成本累计</p>
            <Sparkline :values="costHist" />
          </div>
        </div>
        <h2 class="sec">渠道状态</h2>
        <p v-if="!tick?.channels.length" class="hint">暂无渠道。</p>
        <div v-for="c in tick?.channels ?? []" :key="c.id" class="crow">
          <span class="cname">{{ c.name }}</span>
          <span class="badge" :class="c.status">{{ statusText(c.status) }}</span>
          <span class="clat">{{ c.latency_p95 === null ? '无样本' : `P95 ${c.latency_p95}ms` }}</span>
        </div>
        <p class="note">每 5 秒推送一次；离开页面自动暂停，断线指数退避重连（1s→30s）。</p>
      </section>
    </div>
  </AdminLayout>
</template>

<style scoped>
.stats { padding: 16px 14px 24px; max-width: 860px; margin: 0 auto; }
.page-title { font-size: var(--fs-xl); margin: 0 0 12px; }
.tabs { display: flex; gap: 8px; margin-bottom: 14px; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px;
  border: 1px solid var(--line); border-radius: 18px; background: var(--surface);
  color: var(--t3); font-size: var(--fs-md); cursor: pointer; }
.tabs button.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 700; }
.tabs .app-icon { width: 15px; height: 15px; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--t4); }
.dot.live { background: var(--ok, #22c55e); animation: pulse 1.6s infinite; }
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md);
  padding: 12px 14px; display: flex; flex-direction: column; gap: 3px; }
.card b { font-size: 22px; }
.card span { font-size: var(--fs-cap); color: var(--t3); }
.card.accent b { color: var(--accent); }
.budget { height: 6px; border-radius: 3px; background: var(--surface-2); margin: 10px 0 14px; overflow: hidden; }
.budget i { display: block; height: 100%; background: var(--accent); border-radius: 3px; transition: width .5s; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.chart { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: 10px 12px; }
.ct { font-size: var(--fs-cap); color: var(--t3); margin: 0 0 6px; }
.sec { font-size: var(--fs-md); margin: 18px 0 8px; }
.hint { color: var(--t4); font-size: var(--fs-sm); padding: 10px 0; }
.frow { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: var(--surface);
  border: 1px solid var(--line); border-radius: var(--r-sm); margin-bottom: 6px; }
.fname { flex: 1; min-width: 0; font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fbar { width: 90px; height: 6px; border-radius: 3px; background: var(--err-soft, #fdecea); overflow: hidden; flex-shrink: 0; }
.fbar .up { display: block; height: 100%; background: var(--ok, #22c55e); }
.fnum { font-size: var(--fs-cap); color: var(--t3); flex-shrink: 0; }
.fnum.down { color: var(--err); }
.crow { display: flex; align-items: center; gap: 10px; padding: 9px 10px; background: var(--surface);
  border: 1px solid var(--line); border-radius: var(--r-sm); margin-bottom: 6px; }
.cname { flex: 1; min-width: 0; font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; background: var(--surface-2); color: var(--t3); }
.badge.enabled { background: var(--accent-soft); color: var(--accent); }
.badge.auto_disabled { background: var(--err-soft, #fdecea); color: var(--err); }
.clat { font-size: var(--fs-cap); color: var(--t3); flex-shrink: 0; }
.note { font-size: var(--fs-cap); color: var(--t4); margin-top: 14px; }
.trend { margin-top: 16px; }
.trend-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.trend-head .sec { margin: 0; }
.mini-btn { display: inline-flex; align-items: center; gap: 4px; padding: 5px 10px;
  border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--surface);
  color: var(--t2); font-size: var(--fs-cap); cursor: pointer; }
.mini-btn:disabled { opacity: .5; }
.mini-btn .app-icon { width: 13px; height: 13px; }
</style>