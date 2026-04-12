# Coding Eval Grading Guide

This file contains canonical answers for the tasks in `eval/coding_eval/tasks/`.

## Task 01: Duplicate Charge Root Cause

Expected core findings:

- Entry path is `app/api.py:post_checkout()` -> `app/services.py:CheckoutService.submit_checkout()` -> `app/clients.py:PaymentsGateway.capture()`
- The service fetches an existing order by `tenant_id + client_reference`, but only short-circuits if status is `"paid"`
- If the earlier attempt returned `"processing"`, the existing order is reused but the service still calls `capture()` again
- The fallback merchant reference is derived from `request_id` in `_merchant_reference()`
- A retry that arrives with a different `X-Request-Id` creates a different gateway merchant reference
- `docs/incidents.md` explicitly says the gateway dedupes only on merchant reference, so this can become a second charge
- A uniqueness constraint on `client_reference` would not fix the second `capture()` call against the same logical order

Minimum acceptable fix:

- Reuse a stable payment idempotency key across retries, derived from a stable logical key such as `tenant_id + client_reference` or persisted order payment key
- Do not call `capture()` again for an order already marked payment-pending unless resuming by a stored stable gateway reference/idempotency key

Useful regression test:

- first call enters pending/processing
- second call uses a different `X-Request-Id`
- assert the service does not emit a second distinct merchant reference

## Task 02: Cross-Tenant Report Leak

Expected core findings:

- Entry path is `app/api.py:get_report_download()` -> `app/services.py:ReportService.get_download_url()`
- `ReportService.get_download_url()` checks cache before loading the report and before authorization
- Cache key is only `report-url:{report_id}:{fmt}`, which is not actor-scoped or tenant-scoped
- If tenant A primes the cache, tenant B can hit the cached signed URL path and bypass `ReportsRepository.actor_can_view()`
- The leak is timing-sensitive because the cache entry expires after `REPORT_URL_CACHE_TTL_SECONDS`
- Storage ACL speculation is not proven by the repo; the proven bug is the cache short-circuit plus weak cache key

Minimum acceptable fix:

- Authorize before returning cached data, or store only actor/tenant-scoped cache entries
- Best minimal fix is to move the permission check ahead of the cache return and include tenant or actor identity in the cache key

Useful regression test:

- actor A requests report and primes cache
- actor B from another tenant requests same report id before cache expiry
- assert permission denied instead of returning the same URL

## Task 03: Logout-All Still Accepts Old Tokens

Expected core findings:

- Mutation path is `app/api.py:logout_all_sessions()` -> `UsersRepository.bump_auth_epoch()` -> `SessionsRepository.invalidate_user_cache()`
- No durable session revocation happens in that path
- Validation path is `app/api.py:require_access_token()` -> `app/services.py:SessionGuard.validate()`
- `SessionGuard.validate()` compares `claims.auth_epoch` against `session.auth_epoch_snapshot`, not against the current user auth epoch
- `logout_all_sessions()` updates the user auth epoch, but the validator is still consulting the session snapshot, which remains unchanged
- Role changes appear to work because the validator does compare `claims.role_version` to `UsersRepository.get_user(...).role_version`

Minimum acceptable fix:

- Compare token `auth_epoch` against the current user auth epoch, or revoke all durable session rows during logout-all and validate against that durable revocation state
- The smallest aligned fix in this repo is to consult `current_user.auth_epoch` in `SessionGuard.validate()`

Useful regression test:

- issue claims with old auth epoch
- call logout-all to bump user auth epoch
- validate same claims and assert authentication failure

## Task 04: Scheduled Close vs Manual Rebuild Drift

Expected core findings:

- Scheduled path is `app/jobs.py:close_previous_month()` -> `OrdersRepository.list_for_month_close(..., timestamp_field=settings.MONTH_CLOSE_TIMESTAMP_FIELD)`
- `settings.MONTH_CLOSE_TIMESTAMP_FIELD` is `"settled_at"`
- Manual rebuild path is `app/jobs.py:rebuild_month()` -> `OrdersRepository.list_for_month_close(..., timestamp_field="posted_at")`
- The two paths therefore compute the same window shape but filter on different business timestamps
- `docs/incidents.md` and `config/settings.py` state that finance treats `settled_at` as authoritative
- Boundary-heavy discrepancies occur because `posted_at` and `settled_at` can land in different months near month-end

Minimum acceptable fix:

- Make `rebuild_month()` use the same configured timestamp field as scheduled close, namely `settings.MONTH_CLOSE_TIMESTAMP_FIELD`

Useful regression test:

- create a paid order with `posted_at` in one month and `settled_at` in the next
- assert scheduled close and manual rebuild return the same inclusion semantics after the fix
