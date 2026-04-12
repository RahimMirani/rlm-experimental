from datetime import datetime

from app.core import explicit_month_window, month_window_for_close
from app.repositories import OrdersRepository
from config import settings


def close_previous_month(
    *,
    tenant_id: str,
    tenant_tz: str,
    now_utc: datetime,
    orders: OrdersRepository,
) -> list:
    start_utc, end_utc = month_window_for_close(now_utc, tenant_tz)
    return orders.list_for_month_close(
        tenant_id,
        start_utc=start_utc,
        end_utc=end_utc,
        timestamp_field=settings.MONTH_CLOSE_TIMESTAMP_FIELD,
    )


def rebuild_month(
    *,
    tenant_id: str,
    tenant_tz: str,
    month_label: str,
    orders: OrdersRepository,
) -> list:
    start_utc, end_utc = explicit_month_window(month_label, tenant_tz)

    # Legacy rebuild semantics: use posted_at because finance historically
    # reconciled import batches by posting time. This has been kept to avoid
    # changing old backfill output unexpectedly.
    return orders.list_for_month_close(
        tenant_id,
        start_utc=start_utc,
        end_utc=end_utc,
        timestamp_field="posted_at",
    )
