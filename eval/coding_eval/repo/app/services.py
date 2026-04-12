from datetime import UTC, datetime

from app.clients import PaymentsGateway, StorageSigner
from app.core import AuthenticationError, PermissionDenied, TTLCache, request_fingerprint
from app.models import AccessTokenClaims, Actor, CheckoutCommand, OrderRecord
from app.repositories import OrdersRepository, ReportsRepository, SessionsRepository, UsersRepository
from config import settings


class CheckoutService:
    def __init__(self, orders: OrdersRepository, payments: PaymentsGateway):
        self.orders = orders
        self.payments = payments

    def submit_checkout(
        self,
        command: CheckoutCommand,
        *,
        card_token: str,
        actor_id: str,
        request_id: str,
        idempotency_key: str | None,
    ) -> OrderRecord:
        existing = self.orders.get_by_client_reference(command.tenant_id, command.client_reference)
        if existing and existing.status == "paid":
            return existing

        order = existing or self.orders.create_draft(
            tenant_id=command.tenant_id,
            client_reference=command.client_reference,
            amount_cents=command.amount_cents,
            currency=command.currency,
        )

        merchant_reference = self._merchant_reference(
            tenant_id=command.tenant_id,
            order_id=order.id,
            request_id=request_id,
            explicit_key=idempotency_key,
        )
        payment = self.payments.capture(
            amount_cents=command.amount_cents,
            currency=command.currency,
            card_token=card_token,
            merchant_reference=merchant_reference,
        )
        if payment.status == "processing":
            self.orders.mark_payment_pending(
                order.id,
                payment.gateway_reference,
                request_fingerprint(actor_id, request_id),
            )
            return order

        self.orders.mark_paid(order.id, payment.gateway_reference)
        return order

    def _merchant_reference(
        self,
        *,
        tenant_id: str,
        order_id: str,
        request_id: str,
        explicit_key: str | None,
    ) -> str:
        if explicit_key:
            return f"{tenant_id}:{explicit_key}:{order_id}"
        return f"{tenant_id}:{request_id}:{order_id}"


class ReportService:
    def __init__(self, reports: ReportsRepository, storage: StorageSigner, cache: TTLCache):
        self.reports = reports
        self.storage = storage
        self.cache = cache

    def get_download_url(self, actor: Actor, report_id: str, fmt: str) -> str:
        cache_key = f"report-url:{report_id}:{fmt}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        report = self.reports.get_report(report_id)
        if not report or report.status != "ready":
            raise FileNotFoundError(report_id)
        if not self.reports.actor_can_view(actor, report):
            raise PermissionDenied(report_id)

        url = self.storage.sign_download(
            report.storage_key,
            expires_in_seconds=settings.DEFAULT_REPORT_URL_TTL_SECONDS,
        )
        self.cache.set(cache_key, url, settings.REPORT_URL_CACHE_TTL_SECONDS)
        return url


class SessionGuard:
    def __init__(self, sessions: SessionsRepository, users: UsersRepository):
        self.sessions = sessions
        self.users = users

    def validate(self, claims: AccessTokenClaims) -> None:
        session = self.sessions.get_session(claims.session_id)
        if not session or session.revoked_at is not None:
            raise AuthenticationError("session-revoked")

        if session.user_id != claims.user_id or session.tenant_id != claims.tenant_id:
            raise AuthenticationError("session-mismatch")

        if claims.auth_epoch != session.auth_epoch_snapshot:
            raise AuthenticationError("stale-auth-epoch")

        current_user = self.users.get_user(claims.user_id)
        if not current_user:
            raise AuthenticationError("user-missing")
        if claims.role_version != current_user.role_version:
            raise AuthenticationError("stale-role-version")
