import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { icons } from '../theme/icons'
import Sparkline from '../stats/components/Sparkline.vue'

vi.mock('../interfaces/api/client', () => ({
  request: vi.fn(),
  getToken: () => 'test-token',
  ApiError: class extends Error {},
}))

import { request } from '../interfaces/api/client'
import { feedbackApi, searchApi, statsApi } from '../interfaces/api/resources'

const mockReq = request as unknown as ReturnType<typeof vi.fn>

describe('扩展功能图标', () => {
  it('新增 5 枚图标均有图形定义', () => {
    for (const name of ['quote', 'reply-arrow', 'thumbs-up', 'thumbs-down', 'pulse'] as const) {
      expect(icons[name].length, name).toBeGreaterThan(0)
    }
  })
})

describe('反馈与搜索 API', () => {
  beforeEach(() => mockReq.mockReset())

  it('vote 发送 rating 到正确路径并返回状态', async () => {
    mockReq.mockResolvedValue({ data: { state: 'up' } })
    const state = await feedbackApi.vote(42, 'up')
    expect(state).toBe('up')
    expect(mockReq).toHaveBeenCalledWith('/api/messages/42/feedback',
      { method: 'POST', body: { rating: 'up' } })
  })

  it('vote 携带 reason', async () => {
    mockReq.mockResolvedValue({ data: { state: 'down' } })
    await feedbackApi.vote(7, 'down', '答非所问')
    expect(mockReq.mock.calls[0][1].body).toEqual({ rating: 'down', reason: '答非所问' })
  })

  it('search 对中文关键词做 URL 编码', async () => {
    mockReq.mockResolvedValue({ data: { items: [], next_cursor: null } })
    await searchApi.query('量子 计算', 'room', 10)
    expect(mockReq.mock.calls[0][0]).toBe(
      `/api/search?q=${encodeURIComponent('量子 计算')}&scope=room&cursor=10`)
  })

  it('stats.feedback 请求管理员聚合接口', async () => {
    mockReq.mockResolvedValue({ data: { total: { up: 1, down: 0, rate: 1 } } })
    const d = await statsApi.feedback()
    expect(d.total.up).toBe(1)
    expect(mockReq).toHaveBeenCalledWith('/api/admin/stats/feedback')
  })
})

describe('Sparkline 手绘曲线', () => {
  it('按数据点数渲染折线', () => {
    const w = mount(Sparkline, { props: { values: [1, 3, 2, 5] } })
    const pts = w.find('polyline').attributes('points')!.split(' ')
    expect(pts).toHaveLength(4)
    expect(w.find('circle').exists()).toBe(true)
  })

  it('空数据不渲染折线只留基线', () => {
    const w = mount(Sparkline, { props: { values: [] } })
    expect(w.find('polyline').exists()).toBe(false)
    expect(w.find('line').exists()).toBe(true)
  })

  it('全等数据不产生 NaN 坐标', () => {
    const w = mount(Sparkline, { props: { values: [2, 2, 2] } })
    expect(w.find('polyline').attributes('points')).not.toContain('NaN')
  })
})