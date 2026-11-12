import { getToken, request } from './client'
import type { Channel, Conversation, FeedbackStats, Invite, Message, Model, Preset, SearchResult, UploadResult, VisibleModel } from './types'

const list = <T>(p: string) => request<{ items: T[] }>(p).then((r) => r.data.items)

export const channelsApi = {
  list: () => list<Channel>('/api/admin/channels'),
  create: (body: Record<string, unknown>) =>
    request<Channel>('/api/admin/channels', { method: 'POST', body }).then((r) => r.data),
  patch: (id: number, body: Record<string, unknown>) =>
    request<Channel>(`/api/admin/channels/${id}`, { method: 'PATCH', body }).then((r) => r.data),
  remove: (id: number, confirm = false) =>
    request<{ deleted: boolean }>(`/api/admin/channels/${id}?confirm=${confirm}`, { method: 'DELETE' }),
  test: (id: number) =>
    request<{ ok: boolean; latency_ms: number; error_kind: string | null; message: string }>(
      `/api/admin/channels/${id}/test`, { method: 'POST' }).then((r) => r.data),
  sync: (id: number) =>
    request<{ models: string[] }>(`/api/admin/channels/${id}/sync-models`, { method: 'POST' }).then((r) => r.data),
  toggle: (id: number, enabled: boolean, confirm = false) =>
    request<{ status: string; affected_models: string[] }>(
      `/api/admin/channels/${id}/toggle`, { method: 'POST', body: { enabled, confirm } }).then((r) => r.data),
  presets: () => request<Record<string, Preset[]>>('/api/admin/channel-presets').then((r) => r.data),
  health: (id: number) => request<{ samples: { sampled_at: string; latency_ms: number | null; success: boolean; error_code: string | null }[]; fail_rate: number | null }>(
    `/api/admin/channels/${id}/health`).then((r) => r.data),
}

export const modelsApi = {
  list: () => list<Model>('/api/admin/models'),
  visible: () => list<VisibleModel>('/api/models'),
  create: (body: Record<string, unknown>) =>
    request<Model>('/api/admin/models', { method: 'POST', body }).then((r) => r.data),
  patch: (id: number, body: Record<string, unknown>) =>
    request<Model>(`/api/admin/models/${id}`, { method: 'PATCH', body }).then((r) => r.data),
  remove: (id: number) => request<{ deleted: boolean }>(`/api/admin/models/${id}`, { method: 'DELETE' }),
  setDefault: (name: string) =>
    request<{ default: string }>(`/api/admin/models/by-name/${name}/default`, { method: 'POST' }),
  bind: (id: number, channel_id: number, upstream_model: string) =>
    request<{ bound: boolean }>(`/api/admin/models/${id}/channels`,
      { method: 'POST', body: { channel_id, upstream_model } }),
}

export const invitesApi = {
  list: () => list<Invite>('/api/admin/invite-codes'),
  create: (body: Record<string, unknown>) =>
    request<{ codes: string[] }>('/api/admin/invite-codes', { method: 'POST', body }).then((r) => r.data.codes),
  revoke: (id: number) => request<{ revoked: boolean }>(`/api/admin/invite-codes/${id}`, { method: 'DELETE' }),
}

export const conversationsApi = {
  list: () => list<Conversation>('/api/conversations'),
  create: (body: Record<string, unknown>) =>
    request<Conversation>('/api/conversations', { method: 'POST', body }).then((r) => r.data),
  patch: (id: number, body: Record<string, unknown>) =>
    request<{ updated: boolean }>(`/api/conversations/${id}`, { method: 'PATCH', body }),
  remove: (id: number) => request<{ deleted: boolean }>(`/api/conversations/${id}`, { method: 'DELETE' }),
  messages: (id: number) => list<Message>(`/api/conversations/${id}/messages`),
}

export const settingsApi = {
  list: () => list<{ key: string; value: Record<string, unknown>; version: number }>('/api/admin/settings'),
  put: (key: string, value: Record<string, unknown>, version: number) =>
    request<{ key: string; updated: boolean }>(`/api/admin/settings/${key}`,
      { method: 'PUT', body: { value, version } }),
}

export const feedbackApi = {
  vote: (messageId: number, rating: 'up' | 'down', reason?: string) =>
    request<{ state: 'up' | 'down' | 'none' }>(`/api/messages/${messageId}/feedback`,
      { method: 'POST', body: { rating, ...(reason ? { reason } : {}) } }).then((r) => r.data.state),
}

export const searchApi = {
  query: (q: string, scope: 'all' | 'dm' | 'room' = 'all', cursor = 0) =>
    request<{ items: SearchResult[]; next_cursor: number | null }>(
      `/api/search?q=${encodeURIComponent(q)}&scope=${scope}&cursor=${cursor}`).then((r) => r.data),
}

export interface StatsDailyItem {
  stat_date: string; ai_calls: number; total_tokens: number
  cost: number; active_users: number; updated_at: string
}
export const statsApi = {
  feedback: () => request<FeedbackStats>('/api/admin/stats/feedback').then((r) => r.data),
  overview: (days = 30) =>
    request<{ items: StatsDailyItem[] }>(`/api/admin/stats/overview?days=${days}`)
      .then((r) => r.data),
  recompute: () =>
    request<{ days_updated: number }>('/api/admin/stats/recompute', { method: 'POST' })
      .then((r) => r.data),
}

export interface ShareItem {
  id: number; scope: string; conversation_id: number | null; room_id: number | null
  expires_at: string; revoked: boolean; created_at: string; token: string
}

export const sharesApi = {
  create: (body: { scope: 'dm' | 'room'; conversation_id?: number; room_id?: number; days: number }) =>
    request<{ share_id: number; token: string; expires_at: string }>('/api/shares',
      { method: 'POST', body }).then((r) => r.data),
  list: () => request<{ items: ShareItem[] }>('/api/shares').then((r) => r.data.items),
  revoke: (id: number) => request<{ revoked: boolean }>(`/api/shares/${id}`, { method: 'DELETE' }),
}

/** 带鉴权下载导出文件（window.open 无法携带 Authorization 头）。 */
export async function downloadExport(path: string, filename: string): Promise<void> {
  const base = import.meta.env?.VITE_API_BASE ?? ''
  const resp = await fetch(`${base}${path}`, {
    headers: { ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
  })
  if (!resp.ok) throw new Error('导出失败')
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

export const alertsApi = {
  test: () => request<{ sent: boolean }>('/api/admin/alerts/test', { method: 'POST' }),
}

export interface ExperimentItem {
  id: number; model_id: number; channel_a: number; channel_b: number; ratio_a: number
  status: 'running' | 'ended'; started_at: string; ended_at: string | null
  model_name: string; channel_a_name: string; channel_b_name: string
}
export interface ExperimentBucket {
  bucket: 'a' | 'b'; channel_id: number; channel_name: string; calls: number
  avg_total_ms: number; p95_total_ms: number | null; cost: number; up: number; down: number
}
export interface ExperimentReport {
  experiment_id: number; status: string; ratio_a: number
  buckets: ExperimentBucket[]; recommendation: string
}
export const experimentsApi = {
  list: () => request<{ items: ExperimentItem[] }>('/api/admin/experiments').then((r) => r.data.items),
  create: (body: { model_id: number; channel_a: number; channel_b: number; ratio_a: number }) =>
    request<{ experiment_id: number }>('/api/admin/experiments',
      { method: 'POST', body }).then((r) => r.data),
  end: (id: number) => request<{ ended: boolean }>(`/api/admin/experiments/${id}/end`, { method: 'POST' }),
  report: (id: number) => request<ExperimentReport>(`/api/admin/experiments/${id}/report`).then((r) => r.data),
}

export const uploadsApi = {
  /** XHR 上传以支持进度回调；鉴权走 Authorization 头。 */
  upload: (file: File, onProgress: (pct: number) => void): Promise<UploadResult> =>
    new Promise((resolve, reject) => {
      const base = import.meta.env?.VITE_API_BASE ?? ''
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${base}/api/uploads`)
      const tok = getToken()
      if (tok) xhr.setRequestHeader('Authorization', `Bearer ${tok}`)
      xhr.upload.onprogress = (e) => {
        if (e.total > 0) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        try {
          const d = JSON.parse(xhr.responseText)
          if (xhr.status === 200 && d.code === 0) resolve(d.data as UploadResult)
          else reject(new Error(d.message ?? '上传失败'))
        } catch { reject(new Error('上传失败')) }
      }
      xhr.onerror = () => reject(new Error('网络错误，上传失败'))
      const fd = new FormData()
      fd.append('file', file)
      xhr.send(fd)
    }),
}

export interface FriendItem { user_id: number; nickname: string; last_msg: string | null; unread_count: number }
export interface FriendRequest { id: number; user_id: number; nickname: string; status?: string; created_at: string }
export interface UserHit { id: number; nickname: string; email: string | null }
export interface DmMessage {
  id: number; sender_id: number; recipient_id: number; content: string
  attachment_id: number | null; read_at: string | null; created_at: string
  sender_nickname?: string
}
export const friendsApi = {
  search: (q: string) =>
    request<{ items: UserHit[] }>(`/api/users/search?q=${encodeURIComponent(q)}`).then((r) => r.data.items),
  request: (userId: number) =>
    request<{ request_id: number; auto_accepted?: boolean }>('/api/friends/requests',
      { method: 'POST', body: { user_id: userId } }).then((r) => r.data),
  requests: () =>
    request<{ incoming: FriendRequest[]; outgoing: FriendRequest[] }>('/api/friends/requests')
      .then((r) => r.data),
  accept: (id: number) =>
    request<{ status: string }>(`/api/friends/requests/${id}/accept`, { method: 'POST' }),
  reject: (id: number) =>
    request<{ status: string }>(`/api/friends/requests/${id}/reject`, { method: 'POST' }),
  list: () => request<{ items: FriendItem[] }>('/api/friends').then((r) => r.data.items),
  unfriend: (userId: number) =>
    request<{ removed: boolean }>(`/api/friends/${userId}`, { method: 'DELETE' }),
}
export const dmApi = {
  send: (userId: number, content: string, attachmentId?: number | null) =>
    request<{ message_id: number }>(`/api/dm/${userId}/messages`,
      { method: 'POST', body: { content, ...(attachmentId ? { attachment_id: attachmentId } : {}) } })
      .then((r) => r.data),
  list: (userId: number, after = 0) =>
    request<{ items: DmMessage[] }>(`/api/dm/${userId}/messages?after=${after}`).then((r) => r.data.items),
  markRead: (userId: number) =>
    request<{ marked: number }>(`/api/dm/${userId}/read`, { method: 'POST' }).then((r) => r.data),
}
