import { getToken } from './client'

export interface SseEvent { event: string; data: Record<string, any> }

/** 读取 SSE 流：逐块回调，返回是否自然结束。 */
export async function streamSSE(
  path: string, body: unknown, onEvent: (e: SseEvent) => void, signal?: AbortSignal,
): Promise<void> {
  const base = import.meta.env?.VITE_API_BASE ?? ''
  const resp = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    let msg = '请求失败'
    try { msg = (await resp.json()).message ?? msg } catch { /* ignore */ }
    onEvent({ event: 'error', data: { code: 'HTTP_ERROR', message: msg } })
    return
  }
  await readSseBody(resp.body, onEvent)
}

async function readSseBody(body: ReadableStream<Uint8Array>, onEvent: (e: SseEvent) => void): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const chunk of parts) {
      let event = 'message'
      let data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      try { onEvent({ event, data: JSON.parse(data) }) } catch { /* 忽略非 JSON 分片 */ }
    }
  }
}

/** GET 版 SSE（实时看板）：鉴权走 Authorization 头，断开由调用方 signal 控制。 */
export async function streamGetSSE(
  path: string, onEvent: (e: SseEvent) => void, signal?: AbortSignal,
): Promise<void> {
  const base = import.meta.env?.VITE_API_BASE ?? ''
  const resp = await fetch(`${base}${path}`, {
    headers: { ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
    signal,
  })
  if (!resp.ok || !resp.body) {
    let msg = '请求失败'
    try { msg = (await resp.json()).message ?? msg } catch { /* ignore */ }
    onEvent({ event: 'error', data: { code: 'HTTP_ERROR', message: msg } })
    return
  }
  await readSseBody(resp.body, onEvent)
}
