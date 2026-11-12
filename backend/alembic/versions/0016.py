"""EXT-020 文件上传

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
    """)
    op.execute("CREATE INDEX idx_upload_owner ON uploads (owner_id, created_at DESC);")
    op.execute("ALTER TABLE messages ADD COLUMN attachment_id BIGINT REFERENCES uploads(id) ON DELETE SET NULL;")
    op.execute("ALTER TABLE models ADD COLUMN supports_vision BOOLEAN NOT NULL DEFAULT false;")


def downgrade() -> None:
    op.execute("ALTER TABLE models DROP COLUMN IF EXISTS supports_vision;")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS attachment_id;")
    op.execute("DROP TABLE IF EXISTS uploads;")
