<script setup lang="ts">
import AppIcon from '../../components/common/AppIcon.vue'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { request, ApiError } from '../../api/client'
import { useAuthStore } from '../../stores/auth'

type Mode = 'login' | 'register'
const mode = ref<Mode>('login')
const identifier = ref('')
const password = ref('')
const nickname = ref('')
const inviteCode = ref('')
const agreed = ref(true)
const loading = ref(false)
const error = ref('')
const lockSeconds = ref(0)
const banned = ref(false)
const router = useRouter()
const auth = useAuthStore()

const isRegister = computed(() => mode.value === 'register')
const submitLabel = computed(() => (isRegister.value ? '注册并进入' : '登 录'))

function switchMode(m: Mode) { mode.value = m; error.value = '' }

function startLockCountdown(seconds: number) {
  lockSeconds.value = seconds
  const timer = setInterval(() => {
    lockSeconds.value -= 1
    if (lockSeconds.value <= 0) clearInterval(timer)
  }, 1000)
}

async function submit() {
  if (loading.value || lockSeconds.value > 0) return
  error.value = ''
  banned.value = false
  if (!agreed.value) { error.value = '请先阅读并同意用户协议与隐私政策'; return }
  loading.value = true
  try {
    const path = isRegister.value ? '/api/auth/register' : '/api/auth/login'
    const body: Record<string, unknown> = { password: password.value }
    if (identifier.value.includes('@')) body.email = identifier.value
    else body.phone = identifier.value
    if (isRegister.value) {
      body.nickname = nickname.value || '新用户'
      body.invite_code = inviteCode.value
      body.idempotency_key = crypto.randomUUID()
    }
    const res = await request<{ token: string; user: any }>(path, { method: 'POST', body })
    auth.login(res.data.token, res.data.user)
    await router.push('/msgs')
  } catch (e) {
    const err = e as ApiError
    error.value = err.message
    banned.value = err.code === 'ACCOUNT_BANNED'
    if (err.status === 423) {
      const m = /(\d+)\s*秒/.exec(err.message)
      startLockCountdown(m ? Number(m[1]) : 900)
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="brand">
      <div class="logo"><AppIcon name="brand-chat" /></div>
      <div>
        <div class="brand-text">AI 聊天室</div>
        <div class="brand-sub">ChatRoom · 多模型 · 多房间</div>
      </div>
    </div>
    <div class="slogan">进入房间，和 <em>AI</em> 以及其他人一起聊。</div>

    <div class="tabs">
      <button type="button" class="tab" :class="{ active: !isRegister }"
              @click="switchMode('login')">登录</button>
      <button type="button" class="tab" :class="{ active: isRegister }"
              @click="switchMode('register')">注册</button>
    </div>

    <input v-model="identifier" class="field" type="text" placeholder="手机号 / 邮箱" />
    <input v-model="password" class="field" type="password" placeholder="密码" />
    <input v-if="isRegister" v-model="nickname" class="field" type="text" placeholder="昵称" />
    <input v-if="isRegister" v-model="inviteCode" class="field invite-field"
           type="text" placeholder="邀请码（管理员发放，必填）" />

    <label class="agreement">
      <input v-model="agreed" type="checkbox" />
      <span>已阅读<a href="/terms.html" target="_blank" rel="noopener">《用户协议》</a>与<a
        href="/privacy.html" target="_blank" rel="noopener">《隐私政策》</a>，AI 生成内容仅供参考</span>
    </label>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="banned" class="appeal">账号已被停用？请发送邮件至
      <a href="mailto:admin@demo.com?subject=账号申诉">admin@demo.com</a> 说明情况申诉。</p>
    <p v-if="lockSeconds > 0" class="lock">尝试过于频繁，请 {{ lockSeconds }} 秒后重试</p>

    <button type="button" class="submit" :disabled="loading || lockSeconds > 0" @click="submit">
      {{ loading ? '处理中…' : submitLabel }}
    </button>
  </div>
</template>

<style scoped>
.login-page { background: #0b0c0e; color: #fff; padding: 0 24px 40px; min-height: 100dvh; }
.brand { margin-top: 72px; display: flex; align-items: center; gap: 10px; }
.logo { width: 40px; height: 40px; border-radius: 10px; background: #000; border: 1px solid #2a2c30;
  display: flex; align-items: center; justify-content: center; }
.logo .app-icon { width: 22px; height: 22px; color: var(--accent); }
.brand-text { font-size: var(--fs-xl); font-weight: 700; }
.brand-sub { font-size: var(--fs-sm); color: #7a8089; margin-top: 2px; }
.slogan { margin: 24px 0 28px; font-size: var(--fs-lg); font-weight: 600; line-height: 1.5; }
.slogan em { font-style: normal; color: var(--accent); }
.tabs { display: flex; gap: 20px; margin-bottom: 18px; border-bottom: 1px solid #26282c; }
.tab { padding: 0 0 10px; background: none; border: none; cursor: pointer;
  font-size: var(--fs-md); color: #7a8089; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab.active { color: #fff; font-weight: 600; border-bottom-color: var(--accent); }
.field { width: 100%; padding: 11px 12px; margin-bottom: 12px; background: #1a1c1f;
  border: 1px solid #2a2c30; border-radius: var(--r-sm); color: #fff; font-size: var(--fs-md); outline: none; }
.field:focus { border-color: var(--accent); }
.agreement { display: flex; gap: 6px; align-items: flex-start; font-size: var(--fs-cap);
  color: #7a8089; margin: 4px 0 16px; }
.agreement a { color: var(--accent); text-decoration: none; border-bottom: 1px solid currentColor; }
.error { color: var(--err); font-size: var(--fs-sm); margin-bottom: 10px; }
.lock { color: var(--warn); font-size: var(--fs-sm); margin-bottom: 10px; }
.appeal { font-size: var(--fs-cap); color: #7a8089; margin-bottom: 10px; line-height: 1.6; }
.appeal a { color: var(--accent); }
.submit { width: 100%; padding: 12px 0; border: none; border-radius: var(--r-sm);
  background: var(--accent); color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.submit:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
