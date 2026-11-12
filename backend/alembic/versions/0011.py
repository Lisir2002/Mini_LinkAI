"""EXT-010 只读分享表

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
    """)
    op.execute("CREATE INDEX idx_share_creator ON shares (created_by, created_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shares;")
