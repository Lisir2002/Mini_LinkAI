import { defineStore } from 'pinia'
import { ref } from 'vue'

export type Theme = 'light' | 'dark'
const KEY = 'chatroom-theme'

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<Theme>('light')

  function apply(t: Theme) {
    theme.value = t
    document.documentElement.setAttribute('data-theme', t)
    localStorage.setItem(KEY, t)
  }
  function init() {
    const saved = localStorage.getItem(KEY)
    apply(saved === 'dark' ? 'dark' : 'light')
  }
  function toggle() { apply(theme.value === 'dark' ? 'light' : 'dark') }

  return { theme, init, toggle, apply }
})
