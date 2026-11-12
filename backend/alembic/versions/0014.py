"""EXT-018 结构化输出模式

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE rooms ADD COLUMN output_mode VARCHAR(8) NOT NULL DEFAULT 'free'
  CHECK (output_mode IN ('free','json','table','code'));
    """)
    op.execute("ALTER TABLE rooms ADD COLUMN output_schema TEXT;")
    op.execute("ALTER TABLE messages ADD COLUMN output_mode VARCHAR(8);")
    op.execute("ALTER TABLE messages ADD COLUMN output_downgraded BOOLEAN NOT NULL DEFAULT false;")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS output_downgraded;")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS output_mode;")
    op.execute("ALTER TABLE rooms DROP COLUMN IF EXISTS output_schema;")
    op.execute("ALTER TABLE rooms DROP COLUMN IF EXISTS output_mode;")
