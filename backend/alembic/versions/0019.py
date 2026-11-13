"""LinkAI 渠道增强：自动补全开关与协议特性位

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE channels ADD COLUMN auto_complete_url BOOLEAN NOT NULL DEFAULT true;")
    op.execute("ALTER TABLE channels ADD COLUMN options JSONB NOT NULL DEFAULT '{}'::jsonb;")


def downgrade() -> None:
    op.execute("ALTER TABLE channels DROP COLUMN IF EXISTS options;")
    op.execute("ALTER TABLE channels DROP COLUMN IF EXISTS auto_complete_url;")
