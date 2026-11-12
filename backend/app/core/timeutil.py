"""配额日切（PRD 12.1）：服务器在 UTC，但配额日必须按 Asia/Shanghai 计算。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.QUOTA_RESET_TZ)


def quota_date(now: datetime | None = None) -> date:
    moment = now or datetime.now(ZoneInfo("UTC"))
    return moment.astimezone(_tz()).date()


def seconds_until_reset(now: datetime | None = None) -> int:
    moment = (now or datetime.now(ZoneInfo("UTC"))).astimezone(_tz())
    nxt = datetime.combine(moment.date() + timedelta(days=1), datetime.min.time(), tzinfo=_tz())
    return max(int((nxt - moment).total_seconds()), 0)
