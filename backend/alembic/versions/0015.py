"""EXT-014 A/B 路由实验

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
    """)
    op.execute("CREATE UNIQUE INDEX uniq_running_experiment ON route_experiments (model_id) WHERE status = 'running';")
    op.execute("ALTER TABLE usage_logs ADD COLUMN experiment_id BIGINT REFERENCES route_experiments(id) ON DELETE SET NULL;")
    op.execute("ALTER TABLE usage_logs ADD COLUMN bucket VARCHAR(1) CHECK (bucket IN ('a','b'));")


def downgrade() -> None:
    op.execute("ALTER TABLE usage_logs DROP COLUMN IF EXISTS bucket;")
    op.execute("ALTER TABLE usage_logs DROP COLUMN IF EXISTS experiment_id;")
    op.execute("DROP TABLE IF EXISTS route_experiments;")
