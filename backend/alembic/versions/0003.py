"""conversations 与房间三表

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE conversations (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title           VARCHAR(64) NOT NULL DEFAULT '新会话',
  model_id        BIGINT REFERENCES models(id) ON DELETE SET NULL,
  system_prompt   TEXT,
  pinned          BOOLEAN NOT NULL DEFAULT false,
  notify_muted    BOOLEAN NOT NULL DEFAULT false,
  active_call_id  UUID,                    
  context_tokens  INT NOT NULL DEFAULT 0,
  message_count   INT NOT NULL DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)
    op.execute("""
CREATE TABLE rooms (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name               VARCHAR(64) NOT NULL,
  description        VARCHAR(255),
  owner_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  system_prompt      TEXT NOT NULL DEFAULT '',
  model_id           BIGINT REFERENCES models(id) ON DELETE SET NULL,
  access_type        VARCHAR(16) NOT NULL DEFAULT 'public'
                     CHECK (access_type IN ('public','invite_code','approval')),
  invite_code        VARCHAR(16) UNIQUE,
  max_members        INT NOT NULL DEFAULT 50 CHECK (max_members > 0),
  member_count       INT NOT NULL DEFAULT 0,
  daily_token_budget BIGINT NOT NULL DEFAULT 500000,
  ai_status          VARCHAR(16) NOT NULL DEFAULT 'normal'
                     CHECK (ai_status IN ('normal','warning','suspended','closed')),
  ai_trigger         VARCHAR(16) NOT NULL DEFAULT 'mention'
                     CHECK (ai_trigger IN ('mention','every','off')),
  context_window     INT NOT NULL DEFAULT 20,      
  allow_member_invite BOOLEAN NOT NULL DEFAULT true,
  archived           BOOLEAN NOT NULL DEFAULT false,
  version            INT NOT NULL DEFAULT 0,            
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)
    op.execute("""
CREATE TABLE room_members (
  room_id          BIGINT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  user_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role             VARCHAR(16) NOT NULL DEFAULT 'member'
                   CHECK (role IN ('owner','manager','member')),
  muted_until      TIMESTAMPTZ,
  notify_muted     BOOLEAN NOT NULL DEFAULT false,   
  nickname_in_room VARCHAR(32),
  last_read_msg_id BIGINT,
  joined_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (room_id, user_id)
);
    """)
    op.execute("""
CREATE TABLE room_join_requests (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  room_id    BIGINT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message    VARCHAR(255),
  status     VARCHAR(16) NOT NULL DEFAULT 'pending'
             CHECK (status IN ('pending','approved','rejected','expired')),
  decided_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  decided_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE IF EXISTS room_join_requests""")
    op.execute("""DROP TABLE IF EXISTS room_members""")
    op.execute("""DROP TABLE IF EXISTS rooms""")
    op.execute("""DROP TABLE IF EXISTS conversations""")
