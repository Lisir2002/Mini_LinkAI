"""audit_logs / notifications / settings

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE audit_logs (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
  action      VARCHAR(64) NOT NULL,        
  target_type VARCHAR(32),
  target_id   VARCHAR(64),
  detail      JSONB NOT NULL DEFAULT '{}',
  ip          INET,
  trace_id    UUID,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)
    op.execute("""
CREATE TABLE notifications (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type       VARCHAR(32) NOT NULL
             CHECK (type IN ('system','quota_warn','quota_exceeded','room_ai_suspended',
                             'room_join_request','room_invite','mention','admin_action')),
  title      VARCHAR(64) NOT NULL,
  body       VARCHAR(500) NOT NULL DEFAULT '',
  link       VARCHAR(128),                  
  room_id    BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  is_read    BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)
    op.execute("""
CREATE TABLE settings (
  key        VARCHAR(64) PRIMARY KEY,
  value      JSONB NOT NULL,
  version    INT NOT NULL DEFAULT 0,                    
  updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE IF EXISTS settings""")
    op.execute("""DROP TABLE IF EXISTS notifications""")
    op.execute("""DROP TABLE IF EXISTS audit_logs""")
