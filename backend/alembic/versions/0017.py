"""EXT-026 统计预聚合表

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE stats_daily (
  stat_date    DATE PRIMARY KEY,
  ai_calls     BIGINT NOT NULL DEFAULT 0,
  total_tokens BIGINT NOT NULL DEFAULT 0,
  cost         NUMERIC(14,6) NOT NULL DEFAULT 0,
  active_users INT NOT NULL DEFAULT 0,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stats_daily;")
