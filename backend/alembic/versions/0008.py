"""EXT-001 墓碑引用 + EXT-003 消息反馈表

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # EXT-001：reply_to_msg_id 去外键，保留墓碑引用以渲染「已删除」占位；
    # 写入完整性由 quote_service.validate_quote 保证。
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_reply_to_msg_id_fkey;")
    op.execute("""
CREATE TABLE message_feedbacks (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id   BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating       VARCHAR(4) NOT NULL CHECK (rating IN ('up','down')),
  reason       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (message_id, user_id)
);
    """)
    op.execute("CREATE INDEX idx_feedback_message ON message_feedbacks (message_id);")
    op.execute("CREATE INDEX idx_feedback_rating ON message_feedbacks (rating, created_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS message_feedbacks;")
    op.execute("""
ALTER TABLE messages ADD CONSTRAINT messages_reply_to_msg_id_fkey
  FOREIGN KEY (reply_to_msg_id) REFERENCES messages(id) ON DELETE SET NULL;
    """)
