export interface Channel {
  id: number; name: string; type: string; base_url: string; api_key_hint: string
  preset: string | null; supported_params: string[]; weight: number; priority: number
  status: 'enabled' | 'disabled' | 'auto_disabled'; fail_count: number
  cooldown_until: string | null; last_check_at: string | null; last_latency_ms: number | null
  discovered_models: string[] | { id: string }[]; version: number
  auto_complete_url?: boolean
  options?: Record<string, boolean>
}
export interface Model {
  id: number; public_name: string; display_name: string; tier: string; context_limit: number
  max_output_tokens: number; price_input: string | number; price_output: string | number
  enabled: boolean; is_default: boolean; sort_order: number; version: number
  channels?: { channel_id: number; channel_name: string; upstream_model: string }[]
}
export interface Invite {
  id: number; code_masked: string; max_uses: number; used_count: number
  expires_at: string | null; note: string | null; created_at: string
}
export interface Conversation {
  id: number; title: string; model_id: number | null; pinned: boolean; notify_muted: boolean
  context_tokens: number; message_count: number; last_message_at: string | null; created_at: string
}
export interface Quote { id: number; deleted?: boolean; nickname?: string; excerpt?: string }
export interface Message {
  id: number; role: 'user' | 'assistant' | 'system'; content: string; status: string
  total_tokens: number | null; created_at: string
  reply_to_msg_id?: number | null; quote?: Quote | null
  attachment_id?: number | null
}
export interface SearchResult {
  message_id: number; scope: 'dm' | 'room'; conversation_id: number | null; room_id: number | null
  title: string; snippet: string; match: string; created_at: string
}
export interface FeedbackStats {
  total: { up: number; down: number; rate: number | null }
  by_model: { id: number; display_name: string; up: number; down: number }[]
  top_rooms: { id: number; name: string; up: number; down: number }[]
}
export interface LiveTick {
  ts: number; online: number; calls_per_min: number
  channels: { id: number; name: string; status: string; fail_count: number; latency_p95: number | null }[]
  budget: { monthly_cost: number; monthly_budget: number; last_hour_cost: number }
}
export interface VisibleModel {
  public_name: string; display_name: string; tier: string; context_limit: number
  price_input: string | number; price_output: string | number; is_default: boolean
}
export interface Preset {
  name: string; base_url: string; supported_params: string[]
  timeout_first_token_ms: number; timeout_total_ms: number
}

export interface UploadResult {
  id: number; url: string; filename: string; content_type: string
  size_bytes: number; kind: 'image' | 'file'
}
