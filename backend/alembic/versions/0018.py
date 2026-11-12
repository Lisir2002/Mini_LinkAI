"""FR-001/003 好友关系与私聊消息

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
    """)
    op.execute("CREATE INDEX idx_friend_addressee ON friendships (addressee_id, status);")
    op.execute("CREATE INDEX idx_friend_requester ON friendships (requester_id, status);")
    op.execute("""
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
    """)
    op.execute("CREATE INDEX idx_dm_pair ON direct_messages (LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id), id DESC);")
    op.execute("CREATE INDEX idx_dm_unread ON direct_messages (recipient_id) WHERE read_at IS NULL;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS direct_messages;")
    op.execute("DROP TABLE IF EXISTS friendships;")
