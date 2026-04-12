DEFAULT_REPORT_URL_TTL_SECONDS = 300
REPORT_URL_CACHE_TTL_SECONDS = 240

# Finance policy: scheduled and rebuilt month-close jobs must both use settled
# money, not merely posted or created records.
MONTH_CLOSE_TIMESTAMP_FIELD = "settled_at"

# The checkout API may receive retries from browsers, mobile clients, CDNs,
# and load balancers. Any retry-safe key must be stable across those layers.
CHECKOUT_RETRY_WINDOW_SECONDS = 900

# Access tokens carry both auth_epoch and role_version. A token should stop
# working after logout-all or role changes.
ACCESS_TOKEN_FIELDS = (
    "user_id",
    "tenant_id",
    "session_id",
    "auth_epoch",
    "role_version",
    "issued_at",
)
