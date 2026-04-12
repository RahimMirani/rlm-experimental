# Incident Notes

These are condensed notes from support and operations. They are not guaranteed to identify the root cause correctly.

## INC-1042: Duplicate card charges after retry

- Affected flow: checkout
- Symptom: some customers see two successful card captures after a gateway timeout banner
- Common pattern:
  - first request appears to hang or returns an uncertain outcome
  - client retries through a CDN or mobile app
  - second attempt sometimes becomes a second charge
- Notes:
  - support initially suspected missing unique constraint on `client_reference`
  - payment processor says they dedupe only by the merchant reference they receive
  - examples often show a different `X-Request-Id` between the first and second attempt

## INC-1188: Wrong user can sometimes download a report link

- Affected flow: report exports
- Symptom: support reproduced a case where a tenant B user could open a fresh signed URL for a tenant A report immediately after tenant A opened the same export
- Notes:
  - direct report lookup still appears tenant-scoped
  - issue is timing-sensitive and disappears after a few minutes
  - first responders thought object storage ACLs were too broad

## INC-1211: Logout-all does not kick out existing bearer tokens

- Affected flow: account security
- Symptom: after "logout all sessions", some already-issued bearer tokens continue to work until natural expiry
- Notes:
  - new logins reflect the new auth epoch correctly
  - role changes invalidate tokens as expected
  - browser sessions that hit the session table directly are more reliable than older mobile tokens

## INC-1299: Finance rerun disagrees with scheduled month-close

- Affected flow: finance closing and backfills
- Symptom: a manual rebuild for the same tenant and month can disagree with the scheduled close
- Notes:
  - discrepancy clusters around transactions that post near the month boundary
  - the finance team considers `settled_at` authoritative for revenue recognition
  - APAC tenants noticed the issue first, but the semantics concern is global
