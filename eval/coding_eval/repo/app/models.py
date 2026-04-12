from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CheckoutCommand:
    tenant_id: str
    cart_id: str
    client_reference: str
    amount_cents: int
    currency: str


@dataclass
class OrderRecord:
    id: str
    tenant_id: str
    client_reference: str
    amount_cents: int
    currency: str
    status: str
    payment_reference: Optional[str] = None
    last_request_fingerprint: Optional[str] = None
    created_at: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None


@dataclass
class Actor:
    user_id: str
    tenant_id: str
    is_staff: bool = False
    role_version: int = 1


@dataclass
class ReportRecord:
    report_id: str
    tenant_id: str
    storage_key: str
    status: str


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    tenant_id: str
    auth_epoch_snapshot: int
    role_version_snapshot: int
    revoked_at: Optional[datetime] = None


@dataclass
class AccessTokenClaims:
    user_id: str
    tenant_id: str
    session_id: str
    auth_epoch: int
    role_version: int
    issued_at: datetime


@dataclass
class UserRecord:
    user_id: str
    tenant_id: str
    auth_epoch: int
    role_version: int
