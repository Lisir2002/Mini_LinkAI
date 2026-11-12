import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RoomSocket } from '../composables/roomSocket'

class FakeWS {
  static instances: FakeWS[] = []
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  readyState = 0
  constructor(public url: string) { FakeWS.instances.push(this) }
  send(d: string) { this.sent.push(d) }
  close() { this.readyState = 3; this.onclose?.() }
  open() { this.readyState = 1; this.onopen?.() }
  emit(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }) }
}

function make(opts: Partial<ConstructorParameters<typeof RoomSocket>[0]> = {}) {
  const messages: any[] = []
  const online: number[] = []
  const fallback: boolean[] = []
  const socket = new RoomSocket({
    rid: 7,
    token: () => 'tok',
    onMessage: (m) => messages.push(m),
    onOnline: (n) => online.push(n),
    onFallback: (a) => fallback.push(a),
    wsFactory: (url) => new FakeWS(url) as unknown as WebSocket,
    ...opts,
  })
  return { socket, messages, online, fallback }
}

beforeEach(() => { vi.useFakeTimers(); FakeWS.instances = [] })
afterEach(() => { vi.useRealTimers() })

describe('RoomSocket', () => {
  it('URL 携带房间号与 token', () => {
    const { socket } = make()
    socket.start()
    expect(FakeWS.instances[0].url).toContain('/ws/rooms/7?token=tok')
  })

  it('分发 message 与 online 事件', () => {
    const { socket, messages, online } = make()
    socket.start()
    const ws = FakeWS.instances[0]
    ws.open()
    ws.emit({ type: 'message', message: { id: 1, content: 'hi' } })
    ws.emit({ type: 'online', count: 3 })
    ws.emit({ type: 'ping' })
    expect(messages).toEqual([{ id: 1, content: 'hi' }])
    expect(online).toEqual([3])
  })

  it('断开进入轮询兜底并按 1s→2s 指数退避重连', () => {
    const { socket, fallback } = make()
    socket.start()
    FakeWS.instances[0].open()
    FakeWS.instances[0].close()
    expect(fallback.at(-1)).toBe(true)
    expect(FakeWS.instances).toHaveLength(1)
    vi.advanceTimersByTime(999)
    expect(FakeWS.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeWS.instances).toHaveLength(2)
    FakeWS.instances[1].close()
    vi.advanceTimersByTime(1999)
    expect(FakeWS.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeWS.instances).toHaveLength(3)
  })

  it('重连成功退出兜底并重置退避', () => {
    const { socket, fallback } = make()
    socket.start()
    FakeWS.instances[0].open()
    FakeWS.instances[0].close()
    vi.advanceTimersByTime(1000)
    FakeWS.instances[1].open()
    expect(fallback.at(-1)).toBe(false)
    FakeWS.instances[1].close()
    vi.advanceTimersByTime(1000)
    expect(FakeWS.instances).toHaveLength(3), '退避应重置回 1s'
  })

  it('stop 后不再重连', () => {
    const { socket } = make()
    socket.start()
    FakeWS.instances[0].open()
    socket.stop()
    vi.advanceTimersByTime(60000)
    expect(FakeWS.instances).toHaveLength(1)
  })

  it('连接期间每 25s 发送心跳', () => {
    const { socket } = make()
    socket.start()
    const ws = FakeWS.instances[0]
    ws.open()
    vi.advanceTimersByTime(25000)
    expect(ws.sent).toContain('ping')
  })
})