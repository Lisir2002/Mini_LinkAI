import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const requestMock = vi.fn()
vi.mock('../api/client', async () => {
  const actual = await vi.importActual<any>('../api/client')
  return { ...actual, request: (...a: unknown[]) => requestMock(...a) }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

async function mountLogin() {
  const Login = (await import('../views/mobile/Login.vue')).default
  return mount(Login, { global: { plugins: [createPinia()] } })
}

describe('登录注册页', () => {
  beforeEach(() => { requestMock.mockReset(); setActivePinia(createPinia()) })

  it('默认登录态不显示邀请码，切到注册后显示', async () => {
    const w = await mountLogin()
    expect(w.find('.invite-field').exists()).toBe(false)
    await w.findAll('.tab')[1].trigger('click')
    expect(w.find('.invite-field').exists()).toBe(true)
    expect(w.find('.submit').text()).toContain('注册')
  })

  it('提交时按钮禁用，防重复点击', async () => {
    let resolve: (v: unknown) => void = () => {}
    requestMock.mockReturnValue(new Promise((r) => { resolve = r }))
    const w = await mountLogin()
    await w.find('.submit').trigger('click')
    expect(w.find('.submit').attributes('disabled')).toBeDefined()
    expect(requestMock).toHaveBeenCalledTimes(1)
    await w.find('.submit').trigger('click')
    expect(requestMock).toHaveBeenCalledTimes(1)
    resolve({ data: { token: 't', user: {} } })
  })

  it('业务错误按后端文案展示', async () => {
    const { ApiError } = await vi.importActual<any>('../api/client')
    requestMock.mockRejectedValue(new ApiError(422, 'INVITE_CODE_INVALID', '邀请码无效或已被使用'))
    const w = await mountLogin()
    await w.findAll('.tab')[1].trigger('click')
    await w.find('.submit').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    expect(w.find('.error').text()).toBe('邀请码无效或已被使用')
  })

  it('423 锁定显示倒计时', async () => {
    const { ApiError } = await vi.importActual<any>('../api/client')
    requestMock.mockRejectedValue(new ApiError(423, 'ACCOUNT_LOCKED', '尝试过于频繁，请 900 秒后重试'))
    const w = await mountLogin()
    await w.find('.submit').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    expect(w.find('.lock').text()).toContain('900')
  })

  it('注册请求携带幂等键', async () => {
    requestMock.mockResolvedValue({ data: { token: 't', user: {} } })
    const w = await mountLogin()
    await w.findAll('.tab')[1].trigger('click')
    await w.find('.submit').trigger('click')
    const body = requestMock.mock.calls[0][1].body
    expect(body.idempotency_key).toBeTruthy()
  })
})
