"""EXT-016 房间模板市场

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
    """)
    op.execute("CREATE INDEX idx_template_hot ON room_templates (use_count DESC, id DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS room_templates;")
