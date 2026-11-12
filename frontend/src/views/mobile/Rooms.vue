<script setup lang="ts">
import AppIcon from '../../components/common/AppIcon.vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import NavBar from '../../components/common/NavBar.vue'
import TabBar from '../../components/common/TabBar.vue'
import Chip from '../../components/common/Chip.vue'
import Drawer from '../../components/common/Drawer.vue'
import EmptyState from '../../components/common/EmptyState.vue'
import { roomsApi, templatesApi, type RoomItem, type TemplateItem } from '../../api/rooms'
import { modelsApi } from '../../api/resources'
import type { Model } from '../../api/types'
import { ApiError } from '../../api/client'
import { useToastStore } from '../../stores/toast'

const router = useRouter()
const toast = useToastStore()
const rooms = ref<RoomItem[]>([])
const models = ref<Model[]>([])
const loading = ref(true)
const q = ref('')
const tab = ref<'all' | 'mine' | 'templates'>('all')
const templates = ref<TemplateItem[]>([])
const tplLoading = ref(false)
const cloning = ref<number | null>(null)

async function loadTemplates() {
  tplLoading.value = true
  try { templates.value = (await templatesApi.list(q.value.trim())).items }
  catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { tplLoading.value = false }
}
function switchTab(t: 'all' | 'mine' | 'templates') {
  tab.value = t
  if (t === 'templates') void loadTemplates()
}
async function cloneTpl(t: TemplateItem) {
  cloning.value = t.id
  try {
    const r = await templatesApi.clone(t.id)
    toast.show(`已从模板创建「${r.name}」`, 'success')
    await router.push(`/r/${r.room_id}`)
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { cloning.value = null }
}
const creating = ref(false)
const form = ref({ name: '', description: '', system_prompt: '', model_id: 0, access_type: 'public', max_members: 50 })

const filtered = computed(() => rooms.value.filter((r) => {
  const okQ = !q.value.trim() || r.name.includes(q.value.trim()) || r.description.includes(q.value.trim())
  return okQ && (tab.value === 'all' || r.joined > 0)
}))

async function load() {
  loading.value = true
  try {
    const [rs, ms] = await Promise.all([roomsApi.list(), modelsApi.list().catch(() => [])])
    rooms.value = rs; models.value = ms
    if (!form.value.model_id && ms.length) form.value.model_id = ms[0].id
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { loading.value = false }
}
async function enter(r: RoomItem) {
  try {
    if (!r.joined) { await roomsApi.join(r.id); toast.show(`已加入「${r.name}」`, 'success') }
    await router.push(`/r/${r.id}`)
  } catch (e) { toast.show((e as ApiError).message, 'error') }
}
async function create() {
  if (!form.value.name.trim()) { toast.show('房间名称必填', 'error'); return }
  try {
    const r = await roomsApi.create({ ...form.value, model_id: form.value.model_id || null })
    creating.value = false
    toast.show('房间已创建', 'success')
    await router.push(`/r/${r.id}`)
  } catch (e) { toast.show((e as ApiError).message, 'error') }
}
onMounted(load)
</script>

<template>
  <div class="app-container">
    <NavBar title="列表" sub="房间广场 · 多人 + AI 同聊">
      <template #right>
        <button class="icon-btn" aria-label="创建房间" @click="creating = true">
          <AppIcon name="plus" />
        </button>
      </template>
    </NavBar>
    <div class="search"><AppIcon name="search" />
      <input v-model="q" placeholder="搜索房间名称或简介" /></div>
    <div class="chips">
      <Chip :active="tab === 'all'" @click="tab = 'all'">全部 {{ rooms.length }}</Chip>
      <Chip :active="tab === 'mine'" @click="switchTab('mine')">我加入的 {{ rooms.filter(r => r.joined).length }}</Chip>
      <Chip :active="tab === 'templates'" @click="switchTab('templates')">模板市场</Chip>
    </div>

    <template v-if="tab === 'templates'">
      <p v-if="tplLoading" class="hint">加载中…</p>
      <EmptyState v-else-if="!templates.length" icon="grid" title="还没有模板"
                  desc="房主可以在房间页把成熟配置发布为模板" />
      <article v-for="t in templates" :key="t.id" class="card tpl">
        <div class="top">
          <span class="ric tpl-ic"><AppIcon name="grid" /></span>
          <div class="id">
            <div class="name">{{ t.name }}</div>
            <div class="desc">{{ t.description || '暂无简介' }}</div>
          </div>
          <button class="go" :disabled="cloning === t.id" @click.stop="cloneTpl(t)">
            {{ cloning === t.id ? '创建中…' : '一键开房' }}
          </button>
        </div>
        <div class="meta">
          <span class="pill"><AppIcon name="bolt" />{{ t.model_name ?? '未绑定模型' }}</span>
          <span class="pill"><AppIcon name="people" />上限 {{ t.max_members }}</span>
          <span class="pill"><AppIcon name="refresh" />{{ t.use_count }} 次使用</span>
          <span v-if="t.publisher" class="pill">{{ t.publisher }} 发布</span>
        </div>
      </article>
      <div class="pad-bottom" />
      <TabBar active="rooms" />
    </template>

    <p v-if="loading && tab !== 'templates'" class="hint">加载中…</p>
    <EmptyState v-else-if="tab !== 'templates' && !filtered.length" icon="door-in" title="还没有房间"
                desc="创建一个房间，邀请朋友和 AI 一起讨论">
      <button class="primary sm" @click="creating = true">创建房间</button>
    </EmptyState>

    <article v-for="r in tab === 'templates' ? [] : filtered" :key="r.id" class="card" @click="enter(r)">
      <div class="top">
        <span class="ric"><AppIcon :name="r.ai_trigger === 'off' ? 'brand-chat' : 'group'" /></span>
        <div class="id">
          <div class="name">{{ r.name }}
            <span v-if="r.joined" class="joined">已加入</span>
            <span v-if="r.access_type !== 'public'" class="lock">受限</span>
          </div>
          <div class="desc">{{ r.description || '暂无简介' }}</div>
        </div>
        <button class="go" :class="{ ghost: !r.joined }" @click.stop="enter(r)">
          {{ r.joined ? '进入' : '加入' }}
        </button>
      </div>
      <div class="meta">
        <span class="pill"><AppIcon name="people" />{{ r.member_count }}/{{ r.max_members }}</span>
        <span class="pill"><AppIcon name="bolt" />{{ r.model_name ?? '未绑定模型' }}</span>
        <span class="pill" :class="{ warn: r.ai_status !== 'normal' }">AI {{ r.ai_status }}</span>
      </div>
      <p v-if="r.last_msg" class="last">{{ r.last_msg }}</p>
    </article>

    <template v-if="tab !== 'templates'">
      <div class="pad-bottom" />
      <TabBar active="rooms" />
    </template>

    <Drawer :open="creating" title="创建房间" desc="设定主题提示词与模型，成员 @AI 才会触发调用"
            @close="creating = false">
      <label class="fl">房间名称</label><input v-model="form.name" class="fi" placeholder="例如：翻译室" />
      <label class="fl">简介</label><input v-model="form.description" class="fi" placeholder="一句话说明这个房间做什么" />
      <label class="fl">主题提示词</label>
      <textarea v-model="form.system_prompt" class="fi ta" rows="3"
                placeholder="例如：贴原文即译，术语统一，回答简洁"></textarea>
      <label class="fl">绑定模型</label>
      <select v-model="form.model_id" class="fi">
        <option :value="0">暂不绑定（纯人工讨论）</option>
        <option v-for="m in models" :key="m.id" :value="m.id">{{ m.display_name }}（{{ m.public_name }}）</option>
      </select>
      <div class="two">
        <div><label class="fl">准入方式</label>
          <select v-model="form.access_type" class="fi">
            <option value="public">公开</option><option value="approval">需审批</option>
          </select></div>
        <div><label class="fl">人数上限</label><input v-model.number="form.max_members" class="fi" type="number" /></div>
      </div>
      <template #footer><button class="primary" @click="create">创建房间</button></template>
    </Drawer>
  </div>
</template>

<style scoped>
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.search { position: relative; padding: 8px 12px; background: var(--surface); border-bottom: 1px solid var(--line); }
.search .app-icon { position: absolute; left: 22px; top: 50%; transform: translateY(-50%); width: 17px; height: 17px; color: var(--t4); }
.search input { width: 100%; padding: 8px 12px 8px 34px; background: var(--surface-2); border: 1px solid transparent;
  border-radius: 18px; font-size: var(--fs-md); color: var(--t1); outline: none; }
.chips { display: flex; gap: 6px; padding: 10px 12px 2px; }
.tpl-ic { background: var(--accent-soft); color: var(--accent); }
.card { margin: 8px 16px 0; padding: 12px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-md); cursor: pointer; }
.top { display: flex; align-items: center; gap: 9px; }
.ric { width: 36px; height: 36px; border-radius: var(--r-md); background: var(--accent-soft); color: var(--accent);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.id { flex: 1; min-width: 0; }
.name { font-size: var(--fs-lg); font-weight: 700; display: flex; align-items: center; gap: 5px; }
.joined { font-size: 10px; padding: 1px 5px; border-radius: 3px; background: var(--ok-soft); color: var(--ok); }
.lock { font-size: 10px; padding: 1px 5px; border-radius: 3px; background: var(--warn-soft); color: var(--warn); }
.desc { font-size: var(--fs-sm); color: var(--t3); margin-top: 2px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.go { padding: 6px 14px; border: none; border-radius: 20px; background: var(--accent); color: #fff;
  font-size: var(--fs-cap); font-weight: 600; cursor: pointer; flex-shrink: 0; }
.go.ghost { background: var(--accent-soft); color: var(--accent); }
.meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line); }
.pill { display: inline-flex; align-items: center; gap: 3px; font-size: 10px; padding: 2px 6px;
  border-radius: 3px; background: var(--surface-2); border: 1px solid var(--line); color: var(--t3); }
.pill .app-icon { width: 12px; height: 12px; }
.pill.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn-line); }
.last { font-size: var(--fs-cap); color: var(--t4); margin-top: 7px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 11px 0 4px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.ta { resize: vertical; font-family: inherit; }
.two { display: flex; gap: 8px; }
.two > div { flex: 1; min-width: 0; }
.primary { width: 100%; padding: 12px 0; border: none; border-radius: var(--r-sm); background: var(--accent);
  color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.primary.sm { width: auto; padding: 8px 18px; font-size: var(--fs-md); margin-top: 12px; }
.pad-bottom { height: 72px; }
</style>
