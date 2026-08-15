from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ...core.config import config


ACTIVITY_DAY_START_HOUR = 4


def activity_date(at: datetime | None = None) -> date:
    """Return the activity date for the local 04:00-to-04:00 reporting day."""
    timezone = ZoneInfo(config.timezone)
    if at is None:
        local_time = datetime.now(timezone)
    elif at.tzinfo is None:
        local_time = at.replace(tzinfo=timezone)
    else:
        local_time = at.astimezone(timezone)
    return (local_time - timedelta(hours=ACTIVITY_DAY_START_HOUR)).date()
