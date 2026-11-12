import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

describe('主题 store', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    setActivePinia(createPinia())
  })

  it('默认白天主题', async () => {
    const { useThemeStore } = await import('../stores/theme')
    const t = useThemeStore()
    t.init()
    expect(t.theme).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('切换后写入 DOM 与 localStorage', async () => {
    const { useThemeStore } = await import('../stores/theme')
    const t = useThemeStore()
    t.init()
    t.toggle()
    expect(t.theme).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('chatroom-theme')).toBe('dark')
  })

  it('初始化时读取已保存的选择', async () => {
    localStorage.setItem('chatroom-theme', 'dark')
    const { useThemeStore } = await import('../stores/theme')
    const t = useThemeStore()
    t.init()
    expect(t.theme).toBe('dark')
  })
})
