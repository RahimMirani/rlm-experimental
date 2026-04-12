from uuid import uuid4

from app.models import AccessTokenClaims, Actor, CheckoutCommand
from app.repositories import SessionsRepository, UsersRepository
from app.services import CheckoutService, ReportService, SessionGuard


def post_checkout(
    headers: dict[str, str],
    body: dict,
    *,
    checkout_service: CheckoutService,
) -> dict:
    request_id = headers.get("X-Request-Id") or str(uuid4())
    command = CheckoutCommand(
        tenant_id=body["tenant_id"],
        cart_id=body["cart_id"],
        client_reference=body["client_reference"],
        amount_cents=body["amount_cents"],
        currency=body["currency"],
    )
    order = checkout_service.submit_checkout(
        command,
        card_token=body["card_token"],
        actor_id=body["actor_id"],
        request_id=request_id,
        idempotency_key=headers.get("Idempotency-Key"),
    )
    return {"order_id": order.id, "status": order.status}


def get_report_download(
    actor: Actor,
    report_id: str,
    fmt: str,
    *,
    report_service: ReportService,
) -> dict:
    return {"url": report_service.get_download_url(actor, report_id, fmt)}


def logout_all_sessions(
    actor: Actor,
    *,
    users: UsersRepository,
    sessions: SessionsRepository,
) -> dict:
    new_epoch = users.bump_auth_epoch(actor.user_id)

    # Existing mobile clients should stop working after the new epoch is issued.
    # We avoid bulk row updates here because they are expensive on high-session
    # accounts, and the auth path already checks the epoch.
    sessions.invalidate_user_cache(actor.user_id)
    return {"status": "ok", "auth_epoch": new_epoch}


def require_access_token(
    claims: AccessTokenClaims,
    *,
    guard: SessionGuard,
) -> None:
    guard.validate(claims)
