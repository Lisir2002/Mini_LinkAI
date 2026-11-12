<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AdminLayout from './AdminLayout.vue'
import Switch from '../../theme/components/Switch.vue'
import { settingsApi } from '../../interfaces/api/resources'
import { ApiError } from '../../interfaces/api/client'
import { useToastStore } from '../../core/stores/toast'

const toast = useToastStore()
const loading = ref(true)
const versions = ref<Record<string, number>>({})
const quota = ref({ daily_msg_limit: 50, daily_token_limit: 100000, room_daily_token_budget: 500000, warn_ratio: 0.8 })
const registration = ref({ mode: 'invite_code', require_invite: true })
const moderation = ref({ enabled: true, block_input: true, block_output: true })
const flags = ref({ room_ai: true, web_search: false, voice_input: false, file_upload: false })
const retention = ref({ days: 90 })

async function load() {
  loading.value = true
  try {
    const items = await settingsApi.list()
    for (const it of items) {
      versions.value[it.key] = it.version
      if (it.key === 'quota') Object.assign(quota.value, it.value)
      if (it.key === 'registration') Object.assign(registration.value, it.value)
      if (it.key === 'moderation') Object.assign(moderation.value, it.value)
      if (it.key === 'feature_flags') Object.assign(flags.value, it.value)
      if (it.key === 'retention') Object.assign(retention.value, it.value)
    }
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { loading.value = false }
}
async function save(key: string, value: Record<string, unknown>) {
  try {
    await settingsApi.put(key, value, versions.value[key] ?? 0)
    versions.value[key] = (versions.value[key] ?? 0) + 1
    toast.show('设置已保存，即时生效', 'success')
  } catch (e) {
    toast.show((e as ApiError).message, 'error')
    await load()
  }
}
</script>

<template>
  <AdminLayout>
    <header class="head"><div><h1>系统设置</h1><p>修改后立即生效，无需重启服务</p></div></header>
    <p v-if="loading" class="hint">加载中…</p>

    <section class="card">
      <h2>配额</h2>
      <label class="fl">每人每日消息上限</label>
      <input v-model.number="quota.daily_msg_limit" class="fi" type="number" />
      <label class="fl">每人每日 Token 上限</label>
      <input v-model.number="quota.daily_token_limit" class="fi" type="number" />
      <label class="fl">房间每日 Token 预算</label>
      <input v-model.number="quota.room_daily_token_budget" class="fi" type="number" />
      <label class="fl">预警比例（0-1）</label>
      <input v-model.number="quota.warn_ratio" class="fi" type="number" step="0.05" />
      <button class="primary" @click="save('quota', { ...quota })">保存配额</button>
    </section>

    <section class="card">
      <h2>注册方式</h2>
      <select v-model="registration.mode" class="fi">
        <option value="open">开放注册</option>
        <option value="invite_code">邀请码制</option>
        <option value="closed">仅管理员创建</option>
      </select>
      <p class="note">被刷时可临时切到「仅管理员创建」止血。</p>
      <button class="primary" @click="save('registration', { ...registration, require_invite: registration.mode === 'invite_code' })">
        保存注册方式</button>
    </section>

    <section class="card">
      <h2>内容安全</h2>
      <div class="line"><span>总开关</span><Switch v-model="moderation.enabled" /></div>
      <div class="line"><span>输入侧过滤</span><Switch v-model="moderation.block_input" /></div>
      <div class="line"><span>输出侧过滤</span><Switch v-model="moderation.block_output" /></div>
      <button class="primary" @click="save('moderation', { ...moderation })">保存内容安全</button>
    </section>

    <section class="card">
      <h2>特性开关</h2>
      <div class="line"><span>房间 AI（紧急降级用）</span><Switch v-model="flags.room_ai" /></div>
      <div class="line"><span>联网检索</span><Switch v-model="flags.web_search" /></div>
      <div class="line"><span>语音输入</span><Switch v-model="flags.voice_input" /></div>
      <div class="line"><span>文件上传</span><Switch v-model="flags.file_upload" /></div>
      <button class="primary" @click="save('feature_flags', { ...flags })">保存特性开关</button>
    </section>

    <section class="card">
      <h2>数据保留</h2>
      <label class="fl">消息保留天数</label>
      <input v-model.number="retention.days" class="fi" type="number" />
      <button class="primary" @click="save('retention', { ...retention })">保存保留策略</button>
    </section>
    <div class="pad" />
  </AdminLayout>
</template>

<style scoped>
.head { padding: 14px 16px 10px; }
.head h1 { font-size: var(--fs-xl); font-weight: 700; }
.head p { font-size: var(--fs-cap); color: var(--t3); margin-top: 3px; }
.hint { padding: 24px; text-align: center; color: var(--t4); }
.card { margin: 10px 16px 0; padding: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); }
h2 { font-size: var(--fs-md); font-weight: 700; margin-bottom: 6px; }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 9px 0 4px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.note { font-size: 10px; color: var(--t4); margin-top: 6px; }
.line { display: flex; align-items: center; justify-content: space-between; padding: 8px 0;
  border-bottom: 1px solid var(--line); font-size: var(--fs-md); }
.line:last-of-type { border-bottom: none; }
.primary { width: 100%; margin-top: 12px; padding: 10px 0; border: none; border-radius: var(--r-sm);
  background: var(--accent); color: #fff; font-size: var(--fs-md); font-weight: 600; cursor: pointer; }
.pad { height: 24px; }
</style>
