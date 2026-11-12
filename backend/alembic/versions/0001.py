"""users 与 invite_codes

Revision ID: 0001
Revises: 
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE EXTENSION IF NOT EXISTS citext;
    """)
    op.execute("""
CREATE EXTENSION IF NOT EXISTS pgcrypto;
    """)
    op.execute("""
CREATE TABLE users (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email             CITEXT UNIQUE,
  phone             VARCHAR(20) UNIQUE,
  password_hash     VARCHAR(255) NOT NULL,
  nickname          VARCHAR(32)  NOT NULL,
  role              VARCHAR(16)  NOT NULL DEFAULT 'member'
                    CHECK (role IN ('admin','member')),
  status            VARCHAR(16)  NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','muted','banned')),
  mute_until        TIMESTAMPTZ,
  daily_msg_limit   INT     NOT NULL DEFAULT 50,
  daily_token_limit BIGINT  NOT NULL DEFAULT 100000,
  invited_by        BIGINT  REFERENCES users(id) ON DELETE SET NULL,
  invite_code_used  VARCHAR(24),
  must_change_password BOOLEAN NOT NULL DEFAULT false,   
  last_login_at     TIMESTAMPTZ,
  last_login_ip     INET,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (email IS NOT NULL OR phone IS NOT NULL)
);
    """)
    op.execute("""
COMMENT ON TABLE users IS '全局角色只有 admin/member；房主等房间角色在 room_members';
    """)
    op.execute("""
CREATE TABLE invite_codes (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        VARCHAR(24) NOT NULL UNIQUE,
  created_by  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  max_uses    INT NOT NULL DEFAULT 1 CHECK (max_uses > 0),
  used_count  INT NOT NULL DEFAULT 0,
  expires_at  TIMESTAMPTZ,
  note        VARCHAR(128),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (used_count <= max_uses)
);
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE IF EXISTS invite_codes""")
    op.execute("""DROP TABLE IF EXISTS users""")
