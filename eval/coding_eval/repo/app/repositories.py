from datetime import UTC, datetime

from app.models import Actor, OrderRecord, ReportRecord, SessionRecord, UserRecord


class OrdersRepository:
    """
    Pseudo-SQL shape:

    - get_by_client_reference: select newest order for tenant + client_reference
    - list_for_month_close: filter by the supplied timestamp field
    """

    def get_by_client_reference(self, tenant_id: str, client_reference: str) -> OrderRecord | None:
        ...

    def create_draft(
        self,
        *,
        tenant_id: str,
        client_reference: str,
        amount_cents: int,
        currency: str,
    ) -> OrderRecord:
        ...

    def mark_payment_pending(
        self,
        order_id: str,
        gateway_reference: str,
        request_fingerprint: str,
    ) -> None:
        ...

    def mark_paid(self, order_id: str, gateway_reference: str) -> None:
        ...

    def list_for_month_close(
        self,
        tenant_id: str,
        *,
        start_utc: datetime,
        end_utc: datetime,
        timestamp_field: str,
    ) -> list[OrderRecord]:
        """
        Equivalent query:

        select * from orders
        where tenant_id = :tenant_id
          and {timestamp_field} >= :start_utc
          and {timestamp_field} < :end_utc
          and status = 'paid'
        """
        ...


class ReportsRepository:
    def get_report(self, report_id: str) -> ReportRecord | None:
        ...

    def actor_can_view(self, actor: Actor, report: ReportRecord) -> bool:
        return actor.is_staff or actor.tenant_id == report.tenant_id


class SessionsRepository:
    def get_session(self, session_id: str) -> SessionRecord | None:
        ...

    def revoke_session(self, session_id: str, revoked_at: datetime | None = None) -> None:
        ...

    def revoke_all_for_user(self, user_id: str, revoked_at: datetime | None = None) -> None:
        ...

    def invalidate_user_cache(self, user_id: str) -> None:
        """
        Clears denormalized cache entries keyed by user_id. This does not mutate
        durable session rows.
        """
        ...


class UsersRepository:
    def get_user(self, user_id: str) -> UserRecord | None:
        ...

    def bump_auth_epoch(self, user_id: str) -> int:
        """
        Increment the current user auth epoch and return the new value.
        """
        ...

    def set_role_version(self, user_id: str, role_version: int) -> None:
        ...
