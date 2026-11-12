<script setup lang="ts">
import AppIcon from '../../components/common/AppIcon.vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import NavBar from '../../components/common/NavBar.vue'
import { request, ApiError } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import { useToastStore } from '../../stores/toast'

const auth = useAuthStore()
const toast = useToastStore()
const router = useRouter()
const oldPwd = ref('')
const newPwd = ref('')
const again = ref('')
const busy = ref(false)
const err = ref('')

async function submit() {
  err.value = ''
  if (newPwd.value.length < 8) { err.value = '新密码至少 8 位'; return }
  if (!/[A-Za-z]/.test(newPwd.value) || !/\d/.test(newPwd.value)) { err.value = '新密码需同时包含字母与数字'; return }
  if (newPwd.value !== again.value) { err.value = '两次输入的新密码不一致'; return }
  busy.value = true
  try {
    await request('/api/auth/password', { method: 'POST',
      body: { old_password: oldPwd.value, new_password: newPwd.value } })
    if (auth.user) auth.setUser({ ...auth.user, must_change_password: false })
    toast.show('密码已修改，其他设备需重新登录', 'success')
    await router.push('/msgs')
  } catch (e) { err.value = (e as ApiError).message }
  finally { busy.value = false }
}
</script>
<template>
  <div class="app-container">
    <NavBar title="修改密码" sub="首次登录或管理员重置后必须修改">
      <template #left>
        <button class="icon-btn" aria-label="返回" @click="router.back()">
          <AppIcon name="back" />
        </button>
      </template>
    </NavBar>
    <div class="form">
      <p v-if="auth.user?.must_change_password" class="must">请先修改初始密码，之后才能使用其他功能。</p>
      <label>原密码</label><input v-model="oldPwd" type="password" class="fi" />
      <label>新密码</label><input v-model="newPwd" type="password" class="fi" placeholder="至少 8 位，含字母与数字" />
      <label>确认新密码</label><input v-model="again" type="password" class="fi" />
      <p v-if="err" class="err" role="alert">{{ err }}</p>
      <button class="primary" :disabled="busy" @click="submit">{{ busy ? '提交中…' : '确认修改' }}</button>
    </div>
  </div>
</template>
<style scoped>
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.form { padding: 16px; }
.must { font-size: var(--fs-cap); color: var(--warn); background: var(--warn-soft); padding: 8px 10px;
  border-radius: var(--r-sm); margin-bottom: 14px; line-height: 1.5; }
label { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 10px 0 4px; }
.fi { width: 100%; padding: 10px 12px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.fi:focus { border-color: var(--accent); }
.err { color: var(--err); font-size: var(--fs-sm); margin: 12px 0; }
.primary { width: 100%; margin-top: 16px; padding: 12px 0; border: none; border-radius: var(--r-sm);
  background: var(--accent); color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .5; }
</style>
