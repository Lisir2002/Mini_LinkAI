"""US-003：配置必须覆盖 PRD 20.1 全部变量，缺必填项要指名报错。"""
from __future__ import annotations

import pytest


def test_missing_required_env_names_the_variable(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(Settings, "model_config",
                        {**Settings.model_config, "env_file": None})
    with pytest.raises(ValidationError) as ei:
        Settings()
    assert "JWT_SECRET" in str(ei.value)


def test_settings_expose_prd_business_defaults():
    from app.config import Settings

    s = Settings()
    assert s.DEFAULT_DAILY_MSG_LIMIT == 50
    assert s.DEFAULT_DAILY_TOKEN_LIMIT == 100000
    assert s.DEFAULT_ROOM_DAILY_TOKEN_BUDGET == 500000
    assert s.QUOTA_RESET_TZ == "Asia/Shanghai"
    assert s.AI_FIRST_TOKEN_TIMEOUT_MS == 15000
    assert s.AI_TOTAL_TIMEOUT_MS == 60000
    assert s.REGISTRATION_MODE == "invite_code"
    assert s.DOCS_ENABLED is False
