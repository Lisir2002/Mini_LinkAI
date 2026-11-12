import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { buildRouter } from '../router'

describe('底部三格导航', () => {
  it('恰好三格且顺序为 消息/列表/我的', async () => {
    const TabBar = (await import('../components/common/TabBar.vue')).default
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = buildRouter()
    await router.push('/login')
    await router.isReady()
    const w = mount(TabBar, { props: { active: 'msgs' },
      global: { plugins: [pinia, router] } })
    const items = w.findAll('.tab-item')
    expect(items).toHaveLength(3)
    expect(w.findAll('.tab-label').map((i) => i.text())).toEqual(['消息', '列表', '我的'])
  })

  it('未读角标只在消息格出现', async () => {
    const TabBar = (await import('../components/common/TabBar.vue')).default
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = buildRouter()
    await router.push('/login')
    await router.isReady()
    const w = mount(TabBar, { props: { active: 'msgs', unread: 15 },
      global: { plugins: [pinia, router] } })
    expect(w.findAll('.tab-badge')).toHaveLength(1)
    expect(w.find('.tab-badge').text()).toBe('15')
  })
})
