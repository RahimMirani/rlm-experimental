from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


class PermissionDenied(Exception):
    pass


class AuthenticationError(Exception):
    pass


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class TTLCache:
    def __init__(self):
        self._entries: dict[str, CacheEntry] = {}

    def get(self, key: str, now: datetime | None = None) -> Any | None:
        now = now or datetime.now(UTC)
        entry = self._entries.get(key)
        if not entry:
            return None
        if entry.expires_at <= now:
            self._entries.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self._entries[key] = CacheEntry(value=value, expires_at=now + timedelta(seconds=ttl_seconds))

    def delete_prefix(self, prefix: str) -> None:
        for key in list(self._entries):
            if key.startswith(prefix):
                self._entries.pop(key, None)


def month_window_for_close(now_utc: datetime, tenant_tz: str) -> tuple[datetime, datetime]:
    local_now = now_utc.astimezone(ZoneInfo(tenant_tz))
    end_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_local = (end_local - timedelta(days=1)).replace(day=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def explicit_month_window(month_label: str, tenant_tz: str) -> tuple[datetime, datetime]:
    year, month = month_label.split("-")
    start_local = datetime(int(year), int(month), 1, tzinfo=ZoneInfo(tenant_tz))
    if int(month) == 12:
        end_local = datetime(int(year) + 1, 1, 1, tzinfo=ZoneInfo(tenant_tz))
    else:
        end_local = datetime(int(year), int(month) + 1, 1, tzinfo=ZoneInfo(tenant_tz))
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def request_fingerprint(actor_id: str, request_id: str) -> str:
    return f"{actor_id}:{request_id}"


def bucket_for_day(ts: datetime, tenant_tz: str) -> date:
    return ts.astimezone(ZoneInfo(tenant_tz)).date()
