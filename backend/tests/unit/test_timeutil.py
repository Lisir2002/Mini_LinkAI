"""US-037：配额日必须按 Asia/Shanghai 归属，不能按 UTC。"""
from __future__ import annotations

from datetime import UTC, datetime


def test_utc_1600_belongs_to_next_beijing_day():
    from app.core.timeutil import quota_date

    t = datetime(2026, 11, 11, 16, 0, tzinfo=UTC)   # 北京 11-12 00:00
    assert quota_date(t).isoformat() == "2026-11-12"


def test_utc_1559_still_same_beijing_day():
    from app.core.timeutil import quota_date

    t = datetime(2026, 11, 11, 15, 59, tzinfo=UTC)  # 北京 11-11 23:59
    assert quota_date(t).isoformat() == "2026-11-11"


def test_reset_countdown_at_boundary():
    from app.core.timeutil import seconds_until_reset

    t = datetime(2026, 11, 11, 15, 59, tzinfo=UTC)
    assert 0 < seconds_until_reset(t) <= 60
