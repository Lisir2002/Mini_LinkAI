import { defineStore } from 'pinia'
import { ref } from 'vue'
import { setToken } from '../../interfaces/api/client'

export interface UserInfo {
  id: number
  nickname: string
  email: string
  role: 'admin' | 'member'
  must_change_password: boolean
  daily_msg_limit: number
  daily_token_limit: number
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('chatroom-token'))
  const user = ref<UserInfo | null>(null)

  function setUser(u: UserInfo | null) { user.value = u }
  function login(t: string, u: UserInfo) { token.value = t; setToken(t); user.value = u }
  function logout() { token.value = null; user.value = null; setToken(null) }

  return { token, user, setUser, login, logout }
})
