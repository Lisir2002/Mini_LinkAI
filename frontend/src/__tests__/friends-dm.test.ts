import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  request: vi.fn(),
  getToken: () => 'tok',
  ApiError: class extends Error {},
}))
import { request } from '../api/client'
import { friendsApi, dmApi } from '../api/resources'
import { DmSocket } from '../composables/dmSocket'

const mockReq = request as unknown as ReturnType<typeof vi.fn>

describe('friendsApi / dmApi', () => {
  beforeEach(() => mockReq.mockReset())

  it('搜索用户带编码关键词', async () => {
    mockReq.mockResolvedValue({ data: { items: [] } })
    await friendsApi.search('张 三')
    expect(mockReq).toHaveBeenCalledWith(`/api/users/search?q=${encodeURIComponent('张 三')}`)
  })

  it('发送好友申请', async () => {
    mockReq.mockResolvedValue({ data: { request_id: 1 } })
    await friendsApi.request(9)
    expect(mockReq).toHaveBeenCalledWith('/api/friends/requests', { method: 'POST', body: { user_id: 9 } })
  })

  it('同意/拒绝申请', async () => {
    mockReq.mockResolvedValue({ data: { status: 'accepted' } })
    await friendsApi.accept(3)
    expect(mockReq).toHaveBeenCalledWith('/api/friends/requests/3/accept', { method: 'POST' })
    await friendsApi.reject(4)
    expect(mockReq).toHaveBeenCalledWith('/api/friends/requests/4/reject', { method: 'POST' })
  })

  it('私聊发送与已读', async () => {
    mockReq.mockResolvedValue({ data: { message_id: 1 } })
    await dmApi.send(9, '你好', 5)
    expect(mockReq).toHaveBeenCalledWith('/api/dm/9/messages',
      { method: 'POST', body: { content: '你好', attachment_id: 5 } })
    mockReq.mockResolvedValue({ data: { marked: 2 } })
    await dmApi.markRead(9)
    expect(mockReq).toHaveBeenCalledWith('/api/dm/9/read', { method: 'POST' })
  })
})

class FakeWS {
  static instances: FakeWS[] = []
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor(public url: string) { FakeWS.instances.push(this) }
  send(d: string) { this.sent.push(d) }
  close() { this.onclose?.() }
  open() { this.onopen?.() }
  emit(d: unknown) { this.onmessage?.({ data: JSON.stringify(d) }) }
}

function make() {
  const dms: any[] = []
  const events: any[] = []
  const fallback: boolean[] = []
  const socket = new DmSocket({
    token: () => 'tok',
    onDm: (m) => dms.push(m),
    onEvent: (e) => events.push(e),
    onFallback: (a) => fallback.push(a),
    wsFactory: (u) => new FakeWS(u) as unknown as WebSocket,
  })
  return { socket, dms, events, fallback }
}

beforeEach(() => { vi.useFakeTimers(); FakeWS.instances = [] })
afterEach(() => { vi.useRealTimers() })

describe('DmSocket', () => {
  it('连接 /ws/dm 并分发私聊与好友事件', () => {
    const { socket, dms, events } = make()
    socket.start()
    expect(FakeWS.instances[0].url).toContain('/ws/dm?token=tok')
    const ws = FakeWS.instances[0]
    ws.open()
    ws.emit({ type: 'dm', message: { id: 1, content: 'hi' } })
    ws.emit({ type: 'friend_request', request_id: 2 })
    expect(dms).toEqual([{ id: 1, content: 'hi' }])
    expect(events[0].type).toBe('friend_request')
  })

  it('断线退避重连并切换轮询兜底', () => {
    const { socket, fallback } = make()
    socket.start()
    FakeWS.instances[0].open()
    FakeWS.instances[0].close()
    expect(fallback.at(-1)).toBe(true)
    vi.advanceTimersByTime(1000)
    expect(FakeWS.instances).toHaveLength(2)
    FakeWS.instances[1].open()
    expect(fallback.at(-1)).toBe(false)
    FakeWS.instances[1].close()
    vi.advanceTimersByTime(2000)
    expect(FakeWS.instances).toHaveLength(3)
  })

  it('stop 后不再重连', () => {
    const { socket } = make()
    socket.start()
    FakeWS.instances[0].open()
    socket.stop()
    vi.advanceTimersByTime(60000)
    expect(FakeWS.instances).toHaveLength(1)
  })
})
