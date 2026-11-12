/** EXT-025 房间 WS 客户端：增量推送 + 指数退避重连 + 轮询兜底切换。 */

export interface RoomSocketOptions {
  rid: number
  token: () => string | null
  onMessage: (m: Record<string, unknown>) => void
  onOnline: (count: number) => void
  /** true=WS 断开需启动轮询兜底；false=WS 恢复需停止轮询并补历史 */
  onFallback: (active: boolean) => void
  wsFactory?: (url: string) => WebSocket
}

export class RoomSocket {
  private ws: WebSocket | null = null
  private retry = 1000
  private stopped = false
  private pingTimer: number | undefined
  private retryTimer: number | undefined

  constructor(private opts: RoomSocketOptions) {}

  private url(): string {
    const base = (import.meta.env?.VITE_API_BASE ?? '') as string
    const httpBase = base || location.origin
    const wsBase = httpBase.replace(/^http/, 'ws')
    return `${wsBase}/ws/rooms/${this.opts.rid}?token=${this.opts.token() ?? ''}`
  }

  start(): void {
    this.stopped = false
    this.connect()
  }

  private connect(): void {
    if (this.stopped) return
    const factory = this.opts.wsFactory ?? ((u: string) => new WebSocket(u))
    const ws = factory(this.url())
    this.ws = ws
    ws.onopen = () => {
      this.retry = 1000
      this.opts.onFallback(false)
      this.pingTimer = window.setInterval(() => {
        try { ws.send('ping') } catch { /* 连接将关闭 */ }
      }, 25000)
    }
    ws.onmessage = (ev: MessageEvent) => {
      try {
        const d = JSON.parse(String(ev.data))
        if (d.type === 'message') this.opts.onMessage(d.message)
        else if (d.type === 'online') this.opts.onOnline(Number(d.count))
      } catch { /* 忽略非 JSON 分片 */ }
    }
    ws.onclose = () => {
      this.clearTimers()
      if (!this.stopped) {
        this.opts.onFallback(true)
        this.retryTimer = window.setTimeout(() => this.connect(), this.retry)
        this.retry = Math.min(this.retry * 2, 30000)
      }
    }
    ws.onerror = () => { try { ws.close() } catch { /* 已关闭 */ } }
  }

  stop(): void {
    this.stopped = true
    this.clearTimers()
    try { this.ws?.close() } catch { /* 已关闭 */ }
  }

  private clearTimers(): void {
    window.clearInterval(this.pingTimer)
    window.clearTimeout(this.retryTimer)
  }
}
