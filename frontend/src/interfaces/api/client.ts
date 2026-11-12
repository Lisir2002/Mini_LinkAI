/** 统一请求封装：注入令牌、解析包装、透出 trace_id、401 统一处理。 */
const BASE = import.meta.env?.VITE_API_BASE ?? ''
const TOKEN_KEY = 'chatroom-token'

let token: string | null = localStorage.getItem(TOKEN_KEY)
let unauthorizedHandler: (() => void) | null = null

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string,
              public detail?: Record<string, unknown>, public traceId?: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export function setToken(t: string | null): void {
  token = t
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}
export function getToken(): string | null { return token }
export function onUnauthorized(fn: () => void): void { unauthorizedHandler = fn }

export interface ApiResult<T> { data: T; traceId?: string }
export interface ReqOptions { method?: string; body?: unknown; headers?: Record<string, string> }

export async function request<T>(path: string, opts: ReqOptions = {}): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${BASE}${path}`, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  })
  const traceId = resp.headers.get('X-Request-ID') ?? undefined
  let payload: any = null
  try { payload = await resp.json() } catch { /* 空响应体 */ }
  if (!resp.ok) {
    if (resp.status === 401) {
      setToken(null)
      unauthorizedHandler?.()
    }
    throw new ApiError(resp.status, payload?.code ?? 'INTERNAL',
                       payload?.message ?? '请求失败', payload?.detail, traceId)
  }
  return { data: payload?.data as T, traceId }
}
