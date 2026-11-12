/** FR-006 个人事件 WS：私聊/好友通知 + 指数退避重连 + 轮询兜底。 */

export interface DmSocketOptions {
  token: () => string | null
  onDm: (m: Record<string, unknown>) => void
  onEvent: (e: Record<string, unknown>) => void
  onFallback: (active: boolean) => void
  wsFactory?: (url: string) => WebSocket
}

export class DmSocket {
  private ws: WebSocket | null = null
  private retry = 1000
  private stopped = false
  private pingTimer: number | undefined
  private retryTimer: number | undefined

  constructor(private opts: DmSocketOptions) {}

  private url(): string {
    const base = (import.meta.env?.VITE_API_BASE ?? '') as string
    const httpBase = base || location.origin
    return `${httpBase.replace(/^http/, 'ws')}/ws/dm?token=${this.opts.token() ?? ''}`
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
        if (d.type === 'dm') this.opts.onDm(d.message)
        else if (['friend_request', 'friend_accepted', 'dm_read'].includes(d.type)) this.opts.onEvent(d)
      } catch { /* 忽略非 JSON */ }
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
