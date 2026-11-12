"""EXT-012 渠道健康采样表

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE channel_health_samples (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  channel_id  BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  sampled_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  latency_ms  INT,
  success     BOOLEAN NOT NULL,
  error_code  VARCHAR(32)
);
    """)
    op.execute("CREATE INDEX idx_health_channel_time ON channel_health_samples (channel_id, sampled_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS channel_health_samples;")
