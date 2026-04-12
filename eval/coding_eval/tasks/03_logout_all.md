# Incident Brief 03: Logout-All Still Accepts Old Tokens

Work only from the repository in this workspace.

## Scenario

Security reports incident `INC-1211`: after "logout all sessions", some already-issued bearer tokens continue to work until expiry.

## Request

Explain why that happens.

Your answer must include:

1. The exact `logout-all` mutation path
2. The exact token validation path
3. Why role changes appear to work correctly even though logout-all does not
4. The minimal fix
5. One focused check that would fail before the fix and pass after it

## Important

- It is not enough to say "cache invalidation is broken"
- You must identify which source of truth changes and which one the validator actually consults
