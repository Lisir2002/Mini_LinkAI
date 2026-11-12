"""EXT-009 Token 估算校准表

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE model_tokenizer_drift (
  model_id   BIGINT PRIMARY KEY REFERENCES models(id) ON DELETE CASCADE,
  samples    INT NOT NULL DEFAULT 0,
  ratio      NUMERIC(6,4) NOT NULL DEFAULT 1.0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_tokenizer_drift;")
