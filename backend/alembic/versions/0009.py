"""EXT-005 全文搜索：pg_trgm + GIN 索引

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE INDEX idx_msg_content_trgm ON messages USING gin (content gin_trgm_ops);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_msg_content_trgm;")
