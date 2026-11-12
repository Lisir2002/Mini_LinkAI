import { request } from './client'
import type { Quote } from './types'

export interface RoomItem {
  id: number; name: string; description: string; access_type: string
  member_count: number; max_members: number; ai_status: string; ai_trigger: string
  model_name: string | null; joined: number; last_msg: string | null; created_at: string
}
export interface RoomMessage {
  id: number; role: string; content: string; total_tokens: number | null
  created_at: string; nickname: string | null
  reply_to_msg_id?: number | null; quote?: Quote | null
  output_mode?: string | null; output_downgraded?: boolean
  attachment_id?: number | null
}
export const roomsApi = {
  list: () => request<{ items: RoomItem[] }>('/api/rooms').then((r) => r.data.items),
  create: (body: Record<string, unknown>) =>
    request<{ id: number; name: string }>('/api/rooms', { method: 'POST', body }).then((r) => r.data),
  join: (id: number) => request<{ joined: boolean }>(`/api/rooms/${id}/join`, { method: 'POST' }),
  leave: (id: number) => request<{ left: boolean }>(`/api/rooms/${id}/leave`, { method: 'POST' }),
  messages: (id: number, after = 0) =>
    request<{ items: RoomMessage[]; room: Record<string, any> }>(
      `/api/rooms/${id}/messages?after=${after}`).then((r) => r.data),
  patch: (id: number, body: Record<string, unknown>) =>
    request<{ updated: boolean }>(`/api/rooms/${id}`, { method: 'PATCH', body }),
  send: (id: number, content: string, replyTo?: number | null, attachmentId?: number | null) =>
    request<{ message_id: number }>(`/api/rooms/${id}/messages`,
      { method: 'POST', body: { content, ...(replyTo ? { reply_to_msg_id: replyTo } : {}),
        ...(attachmentId ? { attachment_id: attachmentId } : {}) } }),
}

export interface TemplateItem {
  id: number; name: string; description: string; access_type: string
  max_members: number; use_count: number; created_at: string
  model_name: string | null; publisher: string | null
}
export const templatesApi = {
  list: (q = '', offset = 0) =>
    request<{ items: TemplateItem[]; next_offset: number | null }>(
      `/api/room-templates?q=${encodeURIComponent(q)}&offset=${offset}`).then((r) => r.data),
  publish: (roomId: number) =>
    request<{ template_id: number }>('/api/room-templates',
      { method: 'POST', body: { room_id: roomId } }).then((r) => r.data),
  clone: (id: number) =>
    request<{ room_id: number; name: string }>(`/api/room-templates/${id}/clone`,
      { method: 'POST' }).then((r) => r.data),
  remove: (id: number) =>
    request<{ deleted: boolean }>(`/api/room-templates/${id}`, { method: 'DELETE' }),
}
