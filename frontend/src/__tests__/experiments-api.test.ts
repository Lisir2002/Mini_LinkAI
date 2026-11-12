import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  request: vi.fn(),
  getToken: () => 't',
  ApiError: class extends Error {},
}))
import { request } from '../api/client'
import { experimentsApi } from '../api/resources'

const mockReq = request as unknown as ReturnType<typeof vi.fn>

describe('experimentsApi', () => {
  beforeEach(() => mockReq.mockReset())

  it('create 发送模型/双渠道/比例', async () => {
    mockReq.mockResolvedValue({ data: { experiment_id: 1 } })
    const d = await experimentsApi.create({ model_id: 2, channel_a: 3, channel_b: 4, ratio_a: 30 })
    expect(d.experiment_id).toBe(1)
    expect(mockReq).toHaveBeenCalledWith('/api/admin/experiments', {
      method: 'POST', body: { model_id: 2, channel_a: 3, channel_b: 4, ratio_a: 30 },
    })
  })

  it('list 拉取实验列表', async () => {
    mockReq.mockResolvedValue({ data: { items: [] } })
    await experimentsApi.list()
    expect(mockReq).toHaveBeenCalledWith('/api/admin/experiments')
  })

  it('end 结束实验', async () => {
    mockReq.mockResolvedValue({ data: { ended: true } })
    await experimentsApi.end(7)
    expect(mockReq).toHaveBeenCalledWith('/api/admin/experiments/7/end', { method: 'POST' })
  })

  it('report 拉取分桶报告', async () => {
    mockReq.mockResolvedValue({ data: { buckets: [], recommendation: 'x' } })
    const d = await experimentsApi.report(7)
    expect(d.recommendation).toBe('x')
    expect(mockReq).toHaveBeenCalledWith('/api/admin/experiments/7/report')
  })
})
