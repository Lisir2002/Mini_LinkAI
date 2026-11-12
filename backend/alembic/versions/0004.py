"""usage_logs 与 daily_usage

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE usage_logs (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  call_id       UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,   
  owner_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,   
  room_id       BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  model_id      BIGINT REFERENCES models(id) ON DELETE SET NULL,
  channel_id    BIGINT REFERENCES channels(id) ON DELETE SET NULL,
  
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
  quota_date    DATE NOT NULL,          
  first_token_ms INT,
  total_ms      INT,
  queue_pos     SMALLINT,
  retry_count   SMALLINT NOT NULL DEFAULT 0,
  fail_reason   VARCHAR(255),
  trace_id      UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  settled_at    TIMESTAMPTZ
);
    """)
    op.execute("""
CREATE TABLE daily_usage (
  quota_date        DATE NOT NULL,
  owner_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  room_id           BIGINT REFERENCES rooms(id) ON DELETE CASCADE,  
  msg_count         INT NOT NULL DEFAULT 0,
  ai_call_count     INT NOT NULL DEFAULT 0,
  prompt_tokens     BIGINT NOT NULL DEFAULT 0,
  completion_tokens BIGINT NOT NULL DEFAULT 0,
  total_tokens      BIGINT NOT NULL DEFAULT 0,
  cost              NUMERIC(14,6) NOT NULL DEFAULT 0,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (quota_date, owner_id, room_id)
);
    """)
    op.execute("""
COMMENT ON TABLE daily_usage IS 'room_id 为 NULL 表示用户级配额；非 NULL 表示该房间预算。两者独立累加，取先到者熔断';
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE IF EXISTS daily_usage""")
    op.execute("""DROP TABLE IF EXISTS usage_logs""")
