"""messages

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE messages (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope              VARCHAR(8) NOT NULL CHECK (scope IN ('dm','room')),
  conversation_id    BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  room_id            BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  sender_id          BIGINT REFERENCES users(id) ON DELETE SET NULL,  
  role               VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','system')),
  content            TEXT NOT NULL,
  content_blocked    BOOLEAN NOT NULL DEFAULT false,   
  model_id           BIGINT REFERENCES models(id) ON DELETE SET NULL,
  channel_id         BIGINT REFERENCES channels(id) ON DELETE SET NULL,
  usage_log_id       BIGINT REFERENCES usage_logs(id) ON DELETE SET NULL,
  trigger_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  reply_to_msg_id    BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  prompt_tokens      INT,
  completion_tokens  INT,
  total_tokens       INT,
  cost               NUMERIC(12,6),
  first_token_ms     INT,
  total_ms           INT,
  status             VARCHAR(16) NOT NULL DEFAULT 'ok'
                     CHECK (status IN ('ok','timeout','failed','blocked','refunded','streaming')),
  idempotency_key    UUID,
  generation_id      UUID,               
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
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE IF EXISTS messages""")
