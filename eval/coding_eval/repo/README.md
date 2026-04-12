# Aster Billing Service

This is a compact service repository used for code investigation.

## System Shape

The service handles:

- checkout and payment capture
- signed report exports
- bearer-token session validation
- scheduled and manual finance month-close jobs

## Repo Map

- `app/api.py` contains thin HTTP handlers
- `app/services.py` contains business logic
- `app/repositories.py` contains data access patterns and authorization checks
- `app/clients.py` contains external integrations
- `app/core.py` contains shared primitives and time-window helpers
- `app/jobs.py` contains background jobs
- `config/settings.py` contains runtime policy values
- `docs/incidents.md` contains real-world symptom reports from support/ops

## Important Constraints

- Checkout is expected to be safely retryable
- Report downloads are tenant-scoped and security-sensitive
- `logout-all` is expected to invalidate existing bearer tokens quickly
- Finance considers `settled_at` the source of truth for month-close accounting

## Notes

- The code is intentionally compact rather than production complete
- Some checks are present, but they are not exhaustive
- The repo is coherent enough for tracing logic, not for execution
