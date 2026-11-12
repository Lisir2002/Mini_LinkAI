"""channels / models / model_channels

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE channels (
  id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name                   VARCHAR(64) NOT NULL,
  
  type                   VARCHAR(24) NOT NULL DEFAULT 'openai_compatible'
                         CHECK (type IN ('openai_compatible','anthropic','gemini','custom')),
  preset                 VARCHAR(32),                    
  base_url               VARCHAR(255) NOT NULL,
  api_key_enc            TEXT NOT NULL,                 
  api_key_hint           VARCHAR(16) NOT NULL,          
  discovered_models      JSONB NOT NULL DEFAULT '[]',   
  supported_params       JSONB NOT NULL DEFAULT
                         '["temperature","top_p","max_tokens","stream"]',
  weight                 INT NOT NULL DEFAULT 100 CHECK (weight >= 0),
  priority               INT NOT NULL DEFAULT 0,
  status                 VARCHAR(16) NOT NULL DEFAULT 'enabled'
                         CHECK (status IN ('enabled','disabled','auto_disabled')),
  fail_count             INT NOT NULL DEFAULT 0,
  success_count          INT NOT NULL DEFAULT 0,
  cooldown_until         TIMESTAMPTZ,
  last_check_at          TIMESTAMPTZ,
  last_latency_ms        INT,
  timeout_first_token_ms INT NOT NULL DEFAULT 15000,
  timeout_total_ms       INT NOT NULL DEFAULT 60000,
  remark                 VARCHAR(255),
  version                INT NOT NULL DEFAULT 0,        
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)
    op.execute("""
COMMENT ON COLUMN channels.api_key_enc IS 'Fernet 加密，密钥来自 env CHANNEL_CIPHER_KEY；明文永不落库、永不出接口';
    """)
    op.execute("""
COMMENT ON COLUMN channels.type IS '协议类型：openai_compatible / anthropic / gemini / custom。适配器按此字段分发，与厂商无关';
    """)
    op.execute("""
CREATE TABLE models (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  public_name       VARCHAR(64) NOT NULL UNIQUE,   
  display_name      VARCHAR(64) NOT NULL,
  tier              VARCHAR(16) NOT NULL DEFAULT 'standard'
                    CHECK (tier IN ('fast','standard','premium')),
  context_limit     INT NOT NULL DEFAULT 32768,
  max_output_tokens INT NOT NULL DEFAULT 4096,
  price_input       NUMERIC(12,6) NOT NULL DEFAULT 0,   
  price_output      NUMERIC(12,6) NOT NULL DEFAULT 0,
  currency          CHAR(3) NOT NULL DEFAULT 'CNY',
  enabled           BOOLEAN NOT NULL DEFAULT true,
  is_default        BOOLEAN NOT NULL DEFAULT false,
  sort_order        INT NOT NULL DEFAULT 0,
  version           INT NOT NULL DEFAULT 0,             
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
    """)
    op.execute("""
CREATE TABLE model_channels (
  model_id       BIGINT NOT NULL REFERENCES models(id)   ON DELETE CASCADE,
  channel_id     BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  upstream_model VARCHAR(128) NOT NULL,      
  enabled        BOOLEAN NOT NULL DEFAULT true,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (model_id, channel_id)
);
    """)
    op.execute("""
COMMENT ON TABLE model_channels IS '替代 One API 的 model_mapping JSON：可索引、可外键、路由无需扫 JSONB';
    """)


def downgrade() -> None:
    op.execute("""DROP TABLE IF EXISTS model_channels""")
    op.execute("""DROP TABLE IF EXISTS models""")
    op.execute("""DROP TABLE IF EXISTS channels""")
