import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../interfaces/api/client', () => ({
  request: vi.fn(),
  getToken: () => 't',
  ApiError: class extends Error {},
}))
import { request } from '../interfaces/api/client'
import { statsApi } from '../interfaces/api/resources'

const mockReq = request as unknown as ReturnType<typeof vi.fn>

describe('statsApi 预聚合趋势', () => {
  beforeEach(() => mockReq.mockReset())

  it('overview 按天数拉取预聚合', async () => {
    mockReq.mockResolvedValue({ data: { items: [{ stat_date: '2026-11-12', ai_calls: 5 }] } })
    const d = await statsApi.overview(14)
    expect(d.items[0].ai_calls).toBe(5)
    expect(mockReq).toHaveBeenCalledWith('/api/admin/stats/overview?days=14')
  })

  it('recompute 触发预聚合', async () => {
    mockReq.mockResolvedValue({ data: { days_updated: 2 } })
    const d = await statsApi.recompute()
    expect(d.days_updated).toBe(2)
    expect(mockReq).toHaveBeenCalledWith('/api/admin/stats/recompute', { method: 'POST' })
  })
})
