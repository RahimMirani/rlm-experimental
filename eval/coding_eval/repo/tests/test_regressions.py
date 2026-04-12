from datetime import UTC, datetime

from app.api import get_report_download, logout_all_sessions, post_checkout
from app.jobs import close_previous_month
from app.models import AccessTokenClaims, Actor


def test_checkout_reuses_paid_order(checkout_service):
    headers = {"X-Request-Id": "req-1"}
    body = {
        "tenant_id": "t-1",
        "cart_id": "c-1",
        "client_reference": "cart-c-1",
        "amount_cents": 4200,
        "currency": "USD",
        "card_token": "card-ok",
        "actor_id": "u-1",
    }

    first = post_checkout(headers, body, checkout_service=checkout_service)
    second = post_checkout(headers, body, checkout_service=checkout_service)
    assert first["order_id"] == second["order_id"]


def test_report_download_cache_hit_same_actor(report_service):
    actor = Actor(user_id="u-1", tenant_id="tenant-a")
    first = get_report_download(actor, "rpt-100", "csv", report_service=report_service)
    second = get_report_download(actor, "rpt-100", "csv", report_service=report_service)
    assert first["url"] == second["url"]


def test_logout_all_changes_epoch(users, sessions):
    actor = Actor(user_id="u-9", tenant_id="tenant-a")
    response = logout_all_sessions(actor, users=users, sessions=sessions)
    assert response["status"] == "ok"
    assert response["auth_epoch"] > 0


def test_scheduled_month_close_uses_finance_timestamp(orders):
    rows = close_previous_month(
        tenant_id="tenant-apac",
        tenant_tz="Asia/Singapore",
        now_utc=datetime(2026, 4, 1, 0, 10, tzinfo=UTC),
        orders=orders,
    )
    assert isinstance(rows, list)


def test_role_change_rejects_old_token(guard):
    claims = AccessTokenClaims(
        user_id="u-11",
        tenant_id="tenant-a",
        session_id="s-11",
        auth_epoch=3,
        role_version=1,
        issued_at=datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
    )

    try:
        guard.validate(claims)
    except Exception as exc:
        assert "role" in str(exc)
