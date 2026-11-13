-- 扩展
CREATE EXTENSION IF NOT EXISTS citext;      -- 邮箱大小写不敏感唯一
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- EXT-005 全文搜索 trigram 索引

-- 1. 用户
CREATE TABLE users (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email             CITEXT UNIQUE,
  phone             VARCHAR(20) UNIQUE,
  password_hash     VARCHAR(255) NOT NULL,
  nickname          VARCHAR(32)  NOT NULL,
  role              VARCHAR(16)  NOT NULL DEFAULT 'member'
                    CHECK (role IN ('admin','member')),
  status            VARCHAR(16)  NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','muted','banned')),
  mute_until        TIMESTAMPTZ,
  daily_msg_limit   INT     NOT NULL DEFAULT 50,
  daily_token_limit BIGINT  NOT NULL DEFAULT 100000,
  invited_by        BIGINT  REFERENCES users(id) ON DELETE SET NULL,
  invite_code_used  VARCHAR(24),
  must_change_password BOOLEAN NOT NULL DEFAULT false,   -- 种子 admin 与重置密码后置 true
  last_login_at     TIMESTAMPTZ,
  last_login_ip     INET,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (email IS NOT NULL OR phone IS NOT NULL)
);
COMMENT ON TABLE users IS '全局角色只有 admin/member；房主等房间角色在 room_members';

-- 2. 邀请码
CREATE TABLE invite_codes (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        VARCHAR(24) NOT NULL UNIQUE,
  created_by  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  max_uses    INT NOT NULL DEFAULT 1 CHECK (max_uses > 0),
  used_count  INT NOT NULL DEFAULT 0,
  expires_at  TIMESTAMPTZ,
  note        VARCHAR(128),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (used_count <= max_uses)
);

-- 3. 渠道（上游模型接口凭证）
CREATE TABLE channels (
  id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name                   VARCHAR(64) NOT NULL,
  -- type 表示【协议类型】而非厂商：选定协议后，任何遵守该协议的上游都可直接接入
  type                   VARCHAR(24) NOT NULL DEFAULT 'openai_compatible'
                         CHECK (type IN ('openai_compatible','anthropic','gemini','custom')),
  preset                 VARCHAR(32),                    -- 厂商预设标识，仅界面回显，不参与路由
  base_url               VARCHAR(255) NOT NULL,
  api_key_enc            TEXT NOT NULL,                 -- Fernet 密文
  api_key_hint           VARCHAR(16) NOT NULL,          -- 末 4 位，仅展示用
  discovered_models      JSONB NOT NULL DEFAULT '[]',   -- 同步模型列表的缓存
  supported_params       JSONB NOT NULL DEFAULT
                         '["temperature","top_p","max_tokens","stream"]',
  weight                 INT NOT NULL DEFAULT 100 CHECK (weight >= 0),
  priority               INT NOT NULL DEFAULT 0,
  -- LinkAI 渠道特性：Base URL 自动补全开关 + 协议特性位（迁移 0019 同步）
  auto_complete_url      BOOLEAN NOT NULL DEFAULT true,
  options                JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                 VARCHAR(16) NOT NULL DEFAULT 'enabled'
                         CHECK (status IN ('enabled','disabled','auto_disabled')),
  fail_count             INT NOT NULL DEFAULT 0,
  success_count          INT NOT NULL DEFAULT 0,
  cooldown_until         TIMESTAMPTZ,
  last_check_at          TIMESTAMPTZ,
  last_latency_ms        INT,
  timeout_first_token_ms INT NOT NULL DEFAULT 15000,
  timeout_total_ms       INT NOT NULL DEFAULT 60000,
  remark                 VARCHAR(255),
  version                INT NOT NULL DEFAULT 0,        -- 乐观锁，PATCH 时比对
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN channels.api_key_enc IS 'Fernet 加密，密钥来自 env CHANNEL_CIPHER_KEY；明文永不落库、永不出接口';
COMMENT ON COLUMN channels.type IS '协议类型：openai_compatible / anthropic / gemini / custom。适配器按此字段分发，与厂商无关';

-- 4. 对外模型注册表
CREATE TABLE models (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  public_name       VARCHAR(64) NOT NULL UNIQUE,   -- 对外暴露名，如 smart/fast/qwen-max
  display_name      VARCHAR(64) NOT NULL,
  tier              VARCHAR(16) NOT NULL DEFAULT 'standard'
                    CHECK (tier IN ('fast','standard','premium')),
  context_limit     INT NOT NULL DEFAULT 32768,
  max_output_tokens INT NOT NULL DEFAULT 4096,
  supports_vision   BOOLEAN NOT NULL DEFAULT false,  -- EXT-020 多模态
  price_input       NUMERIC(12,6) NOT NULL DEFAULT 0,   -- 元 / 百万 token
  price_output      NUMERIC(12,6) NOT NULL DEFAULT 0,
  currency          CHAR(3) NOT NULL DEFAULT 'CNY',
  enabled           BOOLEAN NOT NULL DEFAULT true,
  is_default        BOOLEAN NOT NULL DEFAULT false,
  sort_order        INT NOT NULL DEFAULT 0,
  version           INT NOT NULL DEFAULT 0,             -- 乐观锁
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 全局只能有一个默认模型
CREATE UNIQUE INDEX uniq_models_single_default ON models (is_default) WHERE is_default;

-- 5. 模型 ↔ 渠道 绑定（承载"模型名映射"）
CREATE TABLE model_channels (
  model_id       BIGINT NOT NULL REFERENCES models(id)   ON DELETE CASCADE,
  channel_id     BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  upstream_model VARCHAR(128) NOT NULL,      -- 上游真实模型名
  enabled        BOOLEAN NOT NULL DEFAULT true,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (model_id, channel_id)
);
COMMENT ON TABLE model_channels IS '替代 One API 的 model_mapping JSON：可索引、可外键、路由无需扫 JSONB';

-- 6. 单聊会话
CREATE TABLE conversations (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title           VARCHAR(64) NOT NULL DEFAULT '新会话',
  model_id        BIGINT REFERENCES models(id) ON DELETE SET NULL,
  system_prompt   TEXT,
  pinned          BOOLEAN NOT NULL DEFAULT false,
  notify_muted    BOOLEAN NOT NULL DEFAULT false,
  active_call_id  UUID,                    -- 进行中的 AI 调用，非空即表示有流在跑（会话级串行）
  context_tokens  INT NOT NULL DEFAULT 0,
  message_count   INT NOT NULL DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7. 房间
CREATE TABLE rooms (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name               VARCHAR(64) NOT NULL,
  description        VARCHAR(255),
  owner_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  system_prompt      TEXT NOT NULL DEFAULT '',
  model_id           BIGINT REFERENCES models(id) ON DELETE SET NULL,
  access_type        VARCHAR(16) NOT NULL DEFAULT 'public'
                     CHECK (access_type IN ('public','invite_code','approval')),
  invite_code        VARCHAR(16) UNIQUE,
  max_members        INT NOT NULL DEFAULT 50 CHECK (max_members > 0),
  member_count       INT NOT NULL DEFAULT 0,
  daily_token_budget BIGINT NOT NULL DEFAULT 500000,
  ai_status          VARCHAR(16) NOT NULL DEFAULT 'normal'
                     CHECK (ai_status IN ('normal','warning','suspended','closed')),
  ai_trigger         VARCHAR(16) NOT NULL DEFAULT 'mention'
                     CHECK (ai_trigger IN ('mention','every','off')),
  context_window     INT NOT NULL DEFAULT 20,      -- 组装上下文取最近 N 条
  output_mode        VARCHAR(8) NOT NULL DEFAULT 'free'
                     CHECK (output_mode IN ('free','json','table','code')),  -- EXT-018
  output_schema      TEXT,                          -- JSON 模式的 Schema 约束
  allow_member_invite BOOLEAN NOT NULL DEFAULT true,
  archived           BOOLEAN NOT NULL DEFAULT false,
  version            INT NOT NULL DEFAULT 0,            -- 乐观锁（房主与管理员可能同时改）
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. 房间成员
CREATE TABLE room_members (
  room_id          BIGINT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  user_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role             VARCHAR(16) NOT NULL DEFAULT 'member'
                   CHECK (role IN ('owner','manager','member')),
  muted_until      TIMESTAMPTZ,
  notify_muted     BOOLEAN NOT NULL DEFAULT false,   -- 房间免打扰（原型「房间操作」弹层）
  nickname_in_room VARCHAR(32),
  last_read_msg_id BIGINT,
  joined_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (room_id, user_id)
);

-- 9. 入房申请
CREATE TABLE room_join_requests (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  room_id    BIGINT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message    VARCHAR(255),
  status     VARCHAR(16) NOT NULL DEFAULT 'pending'
             CHECK (status IN ('pending','approved','rejected','expired')),
  decided_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  decided_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 同一用户对同一房间只能有一条待审申请（PG15+ NULLS NOT DISTINCT 不适用，用部分唯一索引）
CREATE UNIQUE INDEX uniq_pending_join_request ON room_join_requests (room_id, user_id)
  WHERE status = 'pending';

-- 9b. A/B 路由实验（EXT-014）：同模型两渠道按用户哈希分桶对比
CREATE TABLE route_experiments (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  model_id    BIGINT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  channel_a   BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  channel_b   BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  ratio_a     INT NOT NULL DEFAULT 50 CHECK (ratio_a BETWEEN 1 AND 99),
  status      VARCHAR(8) NOT NULL DEFAULT 'running' CHECK (status IN ('running','ended')),
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at    TIMESTAMPTZ,
  created_by  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  CHECK (channel_a <> channel_b)
);
CREATE UNIQUE INDEX uniq_running_experiment ON route_experiments (model_id) WHERE status = 'running';

-- 10. 用量账本（一次 AI 调用一条）
CREATE TABLE usage_logs (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  call_id       UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- 触发者
  owner_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- 计费归属
  room_id       BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  model_id      BIGINT REFERENCES models(id) ON DELETE SET NULL,
  channel_id    BIGINT REFERENCES channels(id) ON DELETE SET NULL,
  -- 快照字段：模型/渠道被删除后历史统计仍可正确归维度，不依赖 JOIN
  model_public_name  VARCHAR(64),
  model_display_name VARCHAR(64),
  channel_name  VARCHAR(64),
  status        VARCHAR(16) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','settled','refunded','failed')),
  frozen_tokens BIGINT NOT NULL DEFAULT 0,
  prompt_tokens INT,
  completion_tokens INT,
  total_tokens  INT,
  cost          NUMERIC(12,6) NOT NULL DEFAULT 0,
  quota_date    DATE NOT NULL,          -- Asia/Shanghai 当日日期，见 12.1
  first_token_ms INT,
  total_ms      INT,
  queue_pos     SMALLINT,
  retry_count   SMALLINT NOT NULL DEFAULT 0,
  fail_reason   VARCHAR(255),
  experiment_id BIGINT REFERENCES route_experiments(id) ON DELETE SET NULL,
  bucket        VARCHAR(1) CHECK (bucket IN ('a','b')),
  trace_id      UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  settled_at    TIMESTAMPTZ
);

-- 11h. 文件上传（EXT-020）：魔数校验 + UUID 重命名 + 本地隔离存储
CREATE TABLE uploads (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename     VARCHAR(255) NOT NULL,
  stored_name  VARCHAR(64) NOT NULL UNIQUE,
  content_type VARCHAR(64) NOT NULL,
  size_bytes   BIGINT NOT NULL,
  kind         VARCHAR(8) NOT NULL CHECK (kind IN ('image','file')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_upload_owner ON uploads (owner_id, created_at DESC);

-- 11. 消息（单聊与房间共用一张表，scope 区分）
CREATE TABLE messages (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope              VARCHAR(8) NOT NULL CHECK (scope IN ('dm','room')),
  conversation_id    BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  room_id            BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  sender_id          BIGINT REFERENCES users(id) ON DELETE SET NULL,  -- AI 消息为 NULL
  role               VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','system')),
  content            TEXT NOT NULL,
  content_blocked    BOOLEAN NOT NULL DEFAULT false,   -- 命中敏感词被拦截
  model_id           BIGINT REFERENCES models(id) ON DELETE SET NULL,
  channel_id         BIGINT REFERENCES channels(id) ON DELETE SET NULL,
  usage_log_id       BIGINT REFERENCES usage_logs(id) ON DELETE SET NULL,
  trigger_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  reply_to_msg_id    BIGINT,  -- EXT-001 墓碑引用：不加 FK，原消息删除后保留 id 渲染「已删除」占位；写入完整性由 validate_quote 保证
  prompt_tokens      INT,
  completion_tokens  INT,
  total_tokens       INT,
  cost               NUMERIC(12,6),
  first_token_ms     INT,
  total_ms           INT,
  status             VARCHAR(16) NOT NULL DEFAULT 'ok'
                     CHECK (status IN ('ok','timeout','failed','blocked','refunded','streaming')),
  idempotency_key    UUID,
  generation_id      UUID,               -- 重新生成时的代次，旧代流不落库
  attachment_id      BIGINT REFERENCES uploads(id) ON DELETE SET NULL,  -- EXT-020
  output_mode        VARCHAR(8),           -- EXT-018 该条消息实际生效的输出模式
  output_downgraded  BOOLEAN NOT NULL DEFAULT false,  -- JSON 校验两次失败降级标记
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (scope = 'dm'   AND conversation_id IS NOT NULL AND room_id IS NULL) OR
    (scope = 'room' AND room_id IS NOT NULL AND conversation_id IS NULL)
  ),
  CHECK (
    (role = 'assistant' AND sender_id IS NULL) OR
    (role <> 'assistant')
  )
);

-- 11b. 消息反馈（EXT-003）：每人每条消息一票，可改可取消
CREATE TABLE message_feedbacks (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating       VARCHAR(4) NOT NULL CHECK (rating IN ('up','down')),
  reason       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (message_id, user_id)
);
CREATE INDEX idx_feedback_message ON message_feedbacks (message_id);
CREATE INDEX idx_feedback_rating  ON message_feedbacks (rating, created_at DESC);

-- 11c. Token 估算校准（EXT-009）：按模型记录预估/实际偏差的 EMA 修正系数
CREATE TABLE model_tokenizer_drift (
  model_id   BIGINT PRIMARY KEY REFERENCES models(id) ON DELETE CASCADE,
  samples    INT NOT NULL DEFAULT 0,
  ratio      NUMERIC(6,4) NOT NULL DEFAULT 1.0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 11d. 只读分享（EXT-010）：HMAC 签名令牌 + 有效期 + 可撤销
CREATE TABLE shares (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope           VARCHAR(8) NOT NULL CHECK (scope IN ('dm','room')),
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  room_id         BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  created_by      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at      TIMESTAMPTZ NOT NULL,
  revoked         BOOLEAN NOT NULL DEFAULT false,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (scope = 'dm'   AND conversation_id IS NOT NULL AND room_id IS NULL) OR
    (scope = 'room' AND room_id IS NOT NULL AND conversation_id IS NULL)
  )
);
CREATE INDEX idx_share_creator ON shares (created_by, created_at DESC);

-- 11e. 渠道健康采样（EXT-012）：每分钟探测 + 真实调用结果，保留 7 天
CREATE TABLE channel_health_samples (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  channel_id  BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  sampled_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  latency_ms  INT,
  success     BOOLEAN NOT NULL,
  error_code  VARCHAR(32)
);
CREATE INDEX idx_health_channel_time ON channel_health_samples (channel_id, sampled_at DESC);

-- 11f. 房间模板市场（EXT-016）：房主发布成熟配置，他人一键克隆开房
CREATE TABLE room_templates (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name               VARCHAR(64) NOT NULL,
  description        VARCHAR(255) NOT NULL DEFAULT '',
  system_prompt      TEXT NOT NULL DEFAULT '',
  model_id           BIGINT REFERENCES models(id) ON DELETE SET NULL,
  access_type        VARCHAR(16) NOT NULL DEFAULT 'public'
                     CHECK (access_type IN ('public','invite_code','approval')),
  max_members        INT NOT NULL DEFAULT 50 CHECK (max_members > 0),
  daily_token_budget BIGINT NOT NULL DEFAULT 500000,
  ai_trigger         VARCHAR(16) NOT NULL DEFAULT 'mention',
  context_window     INT NOT NULL DEFAULT 20,
  published_by       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source_room_id     BIGINT REFERENCES rooms(id) ON DELETE SET NULL,
  use_count          INT NOT NULL DEFAULT 0,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_template_hot ON room_templates (use_count DESC, id DESC);

-- 11i. 统计预聚合（EXT-026）：调度器把 usage_logs 按日汇总，统计页读预计算
CREATE TABLE stats_daily (
  stat_date    DATE PRIMARY KEY,
  ai_calls     BIGINT NOT NULL DEFAULT 0,
  total_tokens BIGINT NOT NULL DEFAULT 0,
  cost         NUMERIC(14,6) NOT NULL DEFAULT 0,
  active_users INT NOT NULL DEFAULT 0,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 11j. 好友关系（FR-001）：申请→同意，双向查重
CREATE TABLE friendships (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  requester_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  addressee_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status       VARCHAR(8) NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','accepted','rejected','blocked')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (requester_id <> addressee_id),
  UNIQUE (requester_id, addressee_id)
);
CREATE INDEX idx_friend_addressee ON friendships (addressee_id, status);
CREATE INDEX idx_friend_requester ON friendships (requester_id, status);

-- 11k. 私聊消息（FR-003）：仅好友可发，已读未读
CREATE TABLE direct_messages (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sender_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  recipient_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content       TEXT NOT NULL,
  attachment_id BIGINT REFERENCES uploads(id) ON DELETE SET NULL,
  read_at       TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (sender_id <> recipient_id)
);
CREATE INDEX idx_dm_pair ON direct_messages (LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id), id DESC);
CREATE INDEX idx_dm_unread ON direct_messages (recipient_id) WHERE read_at IS NULL;

-- 12. 每日用量汇总（配额判定与统计的数据源，Redis 的重算兜底）
CREATE TABLE daily_usage (
  quota_date        DATE NOT NULL,
  owner_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  room_id           BIGINT REFERENCES rooms(id) ON DELETE CASCADE,  -- NULL = 用户级
  msg_count         INT NOT NULL DEFAULT 0,
  ai_call_count     INT NOT NULL DEFAULT 0,
  prompt_tokens     BIGINT NOT NULL DEFAULT 0,
  completion_tokens BIGINT NOT NULL DEFAULT 0,
  total_tokens      BIGINT NOT NULL DEFAULT 0,
  cost              NUMERIC(14,6) NOT NULL DEFAULT 0,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (quota_date, owner_id, room_id)
);
COMMENT ON TABLE daily_usage IS 'room_id 为 NULL 表示用户级配额；非 NULL 表示该房间预算。两者独立累加，取先到者熔断';

-- 13. 审计日志
CREATE TABLE audit_logs (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
  action      VARCHAR(64) NOT NULL,        -- 如 channel.create / user.ban / room.ai_suspended
  target_type VARCHAR(32),
  target_id   VARCHAR(64),
  detail      JSONB NOT NULL DEFAULT '{}',
  ip          INET,
  trace_id    UUID,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 14. 站内通知（原型消息列表的「系统通知」聚合行）
CREATE TABLE notifications (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type       VARCHAR(32) NOT NULL
             CHECK (type IN ('system','quota_warn','quota_exceeded','room_ai_suspended',
                             'room_join_request','room_invite','mention','admin_action')),
  title      VARCHAR(64) NOT NULL,
  body       VARCHAR(500) NOT NULL DEFAULT '',
  link       VARCHAR(128),                  -- 前端跳转目标，如 /r/7 或 /admin/channels
  room_id    BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  is_read    BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 15. 运行时配置
CREATE TABLE settings (
  key        VARCHAR(64) PRIMARY KEY,
  value      JSONB NOT NULL,
  version    INT NOT NULL DEFAULT 0,                    -- 乐观锁
  updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 查询热点：会话列表、消息翻页、房间消息、用量聚合、审计检索
CREATE INDEX idx_conv_user_last      ON conversations (user_id, last_message_at DESC);
CREATE INDEX idx_msg_conv            ON messages (conversation_id, id DESC);
CREATE INDEX idx_msg_room            ON messages (room_id, id DESC);
CREATE INDEX idx_msg_room_created    ON messages (room_id, created_at DESC);
CREATE INDEX idx_msg_sender          ON messages (sender_id, created_at DESC);
CREATE INDEX idx_room_owner          ON rooms (owner_id);
CREATE INDEX idx_room_active         ON rooms (archived, member_count DESC);
CREATE INDEX idx_room_member_user    ON room_members (user_id, joined_at DESC);
CREATE INDEX idx_joinreq_room_status ON room_join_requests (room_id, status);
CREATE INDEX idx_usage_owner_date    ON usage_logs (owner_id, quota_date);
CREATE INDEX idx_usage_room_date     ON usage_logs (room_id, quota_date);
CREATE INDEX idx_usage_status        ON usage_logs (status) WHERE status = 'pending';
CREATE INDEX idx_usage_created       ON usage_logs (created_at DESC);
CREATE INDEX idx_usage_call          ON usage_logs (call_id);
CREATE INDEX idx_daily_owner         ON daily_usage (owner_id, quota_date DESC);
CREATE INDEX idx_daily_room          ON daily_usage (room_id, quota_date DESC);
CREATE INDEX idx_audit_action_time   ON audit_logs (action, created_at DESC);
CREATE INDEX idx_audit_actor         ON audit_logs (actor_id, created_at DESC);
CREATE INDEX idx_channel_status      ON channels (status, priority DESC, weight DESC);
CREATE INDEX idx_modelchannel_channel ON model_channels (channel_id);
CREATE INDEX idx_invite_unused       ON invite_codes (used_count, expires_at);
CREATE INDEX idx_notify_user_unread  ON notifications (user_id, is_read, created_at DESC);
CREATE INDEX idx_conv_active_call    ON conversations (active_call_id) WHERE active_call_id IS NOT NULL;
-- 幂等：同一用户对同一会话的重复提交
CREATE UNIQUE INDEX uniq_msg_idem    ON messages (idempotency_key) WHERE idempotency_key IS NOT NULL;

-- EXT-005 消息全文搜索（中文子串 ILIKE 走 GIN trigram）
CREATE INDEX idx_msg_content_trgm ON messages USING gin (content gin_trgm_ops);
