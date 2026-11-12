import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

describe('路由守卫', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('未登录访问受保护路由跳登录并带 redirect', async () => {
    const { buildRouter } = await import('../router')
    const router = buildRouter()
    await router.push('/msgs')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/msgs')
  })

  it('非管理员访问后台跳 403', async () => {
    const { useAuthStore } = await import('../stores/auth')
    const { buildRouter } = await import('../router')
    const auth = useAuthStore()
    auth.setUser({ id: 1, nickname: 'u', email: 'u***@x.com', role: 'member',
                   must_change_password: false, daily_msg_limit: 50, daily_token_limit: 1000 })
    auth.token = 'tok'
    const router = buildRouter()
    await router.push('/admin/channels')
    expect(router.currentRoute.value.path).toBe('/403')
  })

  it('首次改密未完成时强制跳改密页', async () => {
    const { useAuthStore } = await import('../stores/auth')
    const { buildRouter } = await import('../router')
    const auth = useAuthStore()
    auth.setUser({ id: 1, nickname: 'a', email: 'a***@x.com', role: 'admin',
                   must_change_password: true, daily_msg_limit: 50, daily_token_limit: 1000 })
    auth.token = 'tok'
    const router = buildRouter()
    await router.push('/msgs')
    expect(router.currentRoute.value.path).toBe('/password')
  })

  it('已登录访问登录页跳消息页', async () => {
    const { useAuthStore } = await import('../stores/auth')
    const { buildRouter } = await import('../router')
    const auth = useAuthStore()
    auth.setUser({ id: 1, nickname: 'u', email: 'u***@x.com', role: 'member',
                   must_change_password: false, daily_msg_limit: 50, daily_token_limit: 1000 })
    auth.token = 'tok'
    const router = buildRouter()
    await router.push('/login')
    expect(router.currentRoute.value.path).toBe('/msgs')
  })
})

describe('刷新后状态恢复', () => {
  beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()) })

  it('有 token 但无 user 时先回拉 /api/auth/me 再判权限', async () => {
    localStorage.setItem('chatroom-token', 'persisted-token')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 0, data: { id: 9, nickname: 'admin', email: 'a***@x.com', role: 'admin',
        must_change_password: false, daily_msg_limit: 50, daily_token_limit: 1000 },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const { buildRouter } = await import('../router')
    const router = buildRouter()
    await router.push('/admin/channels')
    expect(fetchMock).toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/admin/channels')
  })
})
