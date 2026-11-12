"""运行时配置，覆盖 PRD 20.1 全部变量。

必填项（DATABASE_URL / REDIS_URL / JWT_SECRET）缺失时启动即失败并指名变量。
业务默认值可在管理端「系统设置」覆盖，此处仅为初始值。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 基础
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    APP_BASE_URL: str = "http://localhost:8000"
    ACME_EMAIL: str = ""
    DOMAIN: str = "localhost"

    # 数据库
    POSTGRES_DB: str = "ai_chatroom"
    POSTGRES_USER: str = "ai_chatroom"
    POSTGRES_PASSWORD: str = ""
    DATABASE_URL: str
    DB_POOL_SIZE: int = 5          # 每 worker 独立，总量 = workers × (pool+overflow)
    DB_MAX_OVERFLOW: int = 5

    # Redis
    REDIS_PASSWORD: str = ""
    REDIS_URL: str
    REDIS_DB: int = 0

    # 认证密钥
    JWT_SECRET: str
    JWT_SECRET_PREV: str = ""
    JWT_EXPIRE_DAYS: int = 7

    # 渠道 Key 加密
    CHANNEL_CIPHER_KEY: str = ""

    # 业务默认值
    DEFAULT_DAILY_MSG_LIMIT: int = 50
    DEFAULT_DAILY_TOKEN_LIMIT: int = 100000
    DEFAULT_ROOM_DAILY_TOKEN_BUDGET: int = 500000
    QUOTA_WARN_RATIO: float = 0.8
    QUOTA_RESET_TZ: str = "Asia/Shanghai"
    REGISTRATION_MODE: str = "invite_code"
    MODERATION_ENABLED: bool = True
    AI_FIRST_TOKEN_TIMEOUT_MS: int = 15000
    AI_TOTAL_TIMEOUT_MS: int = 60000
    ROOM_AI_COOLDOWN_SEC: int = 5
    ROOM_CONTEXT_WINDOW: int = 20
    ROOM_CONTEXT_TOKEN_LIMIT: int = 8192
    GLOBAL_MONTHLY_BUDGET: float = 200.0

    # 种子渠道（按协议分组）
    SEED_OPENAI_COMPAT_1_NAME: str = ""
    SEED_OPENAI_COMPAT_1_BASE_URL: str = ""
    SEED_OPENAI_COMPAT_1_KEY: str = ""
    SEED_OPENAI_COMPAT_2_NAME: str = ""
    SEED_OPENAI_COMPAT_2_BASE_URL: str = ""
    SEED_OPENAI_COMPAT_2_KEY: str = ""
    SEED_ADMIN_EMAIL: str = ""
    SEED_ADMIN_PASSWORD: str = ""
    SEED_SMART_UPSTREAM_MODEL: str = ""
    SEED_FAST_UPSTREAM_MODEL: str = ""
    SEED_ANTHROPIC_KEY: str = ""
    SEED_GEMINI_KEY: str = ""

    # 备份与监控
    BACKUP_S3_ENDPOINT: str = ""
    BACKUP_S3_BUCKET: str = ""
    BACKUP_S3_ACCESS_KEY: str = ""
    BACKUP_S3_SECRET_KEY: str = ""
    BACKUP_GPG_RECIPIENT: str = ""
    UPTIMEROBOT_NOTIFY_EMAIL: str = ""
    ADMIN_NOTIFY_EMAIL: str = ""

    # 特性开关
    FEATURE_ROOM_AI: bool = True
    FEATURE_WEB_SEARCH: bool = False
    FEATURE_VOICE_INPUT: bool = False
    FEATURE_FILE_UPLOAD: bool = False
    UPLOAD_DIR: str = "var/uploads"  # EXT-020 本地隔离存储目录
    READ_REPLICA_URL: str = ""  # EXT-026 只读副本；空=统计走主库，故障自动回退
    DOCS_ENABLED: bool = False
    CORS_ORIGINS: str = "http://localhost:5173"


settings = Settings()  # type: ignore[call-arg]  # 必填项由 env 提供
