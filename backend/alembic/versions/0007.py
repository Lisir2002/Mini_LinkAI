"""全部索引（27 条）

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE UNIQUE INDEX uniq_models_single_default ON models (is_default) WHERE is_default;
    """)
    op.execute("""
CREATE UNIQUE INDEX uniq_pending_join_request ON room_join_requests (room_id, user_id)
  WHERE status = 'pending';
    """)
    op.execute("""
CREATE INDEX idx_conv_user_last      ON conversations (user_id, last_message_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_msg_conv            ON messages (conversation_id, id DESC);
    """)
    op.execute("""
CREATE INDEX idx_msg_room            ON messages (room_id, id DESC);
    """)
    op.execute("""
CREATE INDEX idx_msg_room_created    ON messages (room_id, created_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_msg_sender          ON messages (sender_id, created_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_room_owner          ON rooms (owner_id);
    """)
    op.execute("""
CREATE INDEX idx_room_active         ON rooms (archived, member_count DESC);
    """)
    op.execute("""
CREATE INDEX idx_room_member_user    ON room_members (user_id, joined_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_joinreq_room_status ON room_join_requests (room_id, status);
    """)
    op.execute("""
CREATE INDEX idx_usage_owner_date    ON usage_logs (owner_id, quota_date);
    """)
    op.execute("""
CREATE INDEX idx_usage_room_date     ON usage_logs (room_id, quota_date);
    """)
    op.execute("""
CREATE INDEX idx_usage_status        ON usage_logs (status) WHERE status = 'pending';
    """)
    op.execute("""
CREATE INDEX idx_usage_created       ON usage_logs (created_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_usage_call          ON usage_logs (call_id);
    """)
    op.execute("""
CREATE INDEX idx_daily_owner         ON daily_usage (owner_id, quota_date DESC);
    """)
    op.execute("""
CREATE INDEX idx_daily_room          ON daily_usage (room_id, quota_date DESC);
    """)
    op.execute("""
CREATE INDEX idx_audit_action_time   ON audit_logs (action, created_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_audit_actor         ON audit_logs (actor_id, created_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_channel_status      ON channels (status, priority DESC, weight DESC);
    """)
    op.execute("""
CREATE INDEX idx_modelchannel_channel ON model_channels (channel_id);
    """)
    op.execute("""
CREATE INDEX idx_invite_unused       ON invite_codes (used_count, expires_at);
    """)
    op.execute("""
CREATE INDEX idx_notify_user_unread  ON notifications (user_id, is_read, created_at DESC);
    """)
    op.execute("""
CREATE INDEX idx_conv_active_call    ON conversations (active_call_id) WHERE active_call_id IS NOT NULL;
    """)
    op.execute("""
CREATE UNIQUE INDEX uniq_msg_idem    ON messages (idempotency_key) WHERE idempotency_key IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""DROP INDEX IF EXISTS uniq_msg_idem""")
    op.execute("""DROP INDEX IF EXISTS idx_conv_active_call""")
    op.execute("""DROP INDEX IF EXISTS idx_notify_user_unread""")
    op.execute("""DROP INDEX IF EXISTS idx_invite_unused""")
    op.execute("""DROP INDEX IF EXISTS idx_modelchannel_channel""")
    op.execute("""DROP INDEX IF EXISTS idx_channel_status""")
    op.execute("""DROP INDEX IF EXISTS idx_audit_actor""")
    op.execute("""DROP INDEX IF EXISTS idx_audit_action_time""")
    op.execute("""DROP INDEX IF EXISTS idx_daily_room""")
    op.execute("""DROP INDEX IF EXISTS idx_daily_owner""")
    op.execute("""DROP INDEX IF EXISTS idx_usage_call""")
    op.execute("""DROP INDEX IF EXISTS idx_usage_created""")
    op.execute("""DROP INDEX IF EXISTS idx_usage_status""")
    op.execute("""DROP INDEX IF EXISTS idx_usage_room_date""")
    op.execute("""DROP INDEX IF EXISTS idx_usage_owner_date""")
    op.execute("""DROP INDEX IF EXISTS idx_joinreq_room_status""")
    op.execute("""DROP INDEX IF EXISTS idx_room_member_user""")
    op.execute("""DROP INDEX IF EXISTS idx_room_active""")
    op.execute("""DROP INDEX IF EXISTS idx_room_owner""")
    op.execute("""DROP INDEX IF EXISTS idx_msg_sender""")
    op.execute("""DROP INDEX IF EXISTS idx_msg_room_created""")
    op.execute("""DROP INDEX IF EXISTS idx_msg_room""")
    op.execute("""DROP INDEX IF EXISTS idx_msg_conv""")
    op.execute("""DROP INDEX IF EXISTS idx_conv_user_last""")
    op.execute("""DROP INDEX IF EXISTS uniq_pending_join_request""")
    op.execute("""DROP INDEX IF EXISTS uniq_models_single_default""")
