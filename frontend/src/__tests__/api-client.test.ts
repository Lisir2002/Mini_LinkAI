import { describe, it, expect, beforeEach, vi } from 'vitest'

describe('API 客户端', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('注入 Authorization 并从环境变量取基址', async () => {
    const { setToken, request } = await import('../interfaces/api/client')
    setToken('tok-123')
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ code: 0, data: { ok: true } }),
      { status: 200, headers: { 'X-Request-ID': 'trace-abc', 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const res = await request<{ ok: boolean }>('/api/auth/me')
    expect(res.data.ok).toBe(true)
    expect(res.traceId).toBe('trace-abc')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-123')
  })

  it('401 清除令牌并触发未授权回调', async () => {
    const { setToken, getToken, request, onUnauthorized, ApiError } = await import('../interfaces/api/client')
    setToken('expired')
    const handler = vi.fn()
    onUnauthorized(handler)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ code: 'TOKEN_EXPIRED', message: '登录已过期' }), { status: 401 })))
    await expect(request('/api/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(getToken()).toBeNull()
    expect(handler).toHaveBeenCalledOnce()
  })

  it('业务错误保留 code 与 message', async () => {
    const { request, ApiError } = await import('../interfaces/api/client')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ code: 'INVITE_CODE_INVALID', message: '邀请码无效或已被使用' }),
      { status: 422 })))
    try {
      await request('/api/auth/register', { method: 'POST', body: {} })
      throw new Error('should have thrown')
    } catch (e) {
      const err = e as InstanceType<typeof ApiError>
      expect(err.code).toBe('INVITE_CODE_INVALID')
      expect(err.status).toBe(422)
      expect(err.message).toBe('邀请码无效或已被使用')
    }
  })

  it('429 透出重试等待秒数', async () => {
    const { request, ApiError } = await import('../interfaces/api/client')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ code: 'ACCOUNT_LOCKED', message: '尝试过于频繁，请 900 秒后重试' }),
      { status: 423 })))
    try {
      await request('/api/auth/login', { method: 'POST', body: {} })
    } catch (e) {
      expect((e as InstanceType<typeof ApiError>).status).toBe(423)
    }
  })
})
