# Incident Brief 02: Cross-Tenant Report Leak

Work only from the repository in this workspace.

## Scenario

Support reports incident `INC-1188`: a tenant B user can sometimes open a signed download URL for a tenant A report, but only shortly after tenant A requested that same export.

## Request

Find the exact security flaw.

Your answer must include:

1. The precise code path that returns the leaked URL
2. The authorization check that should have applied but gets bypassed
3. Why the issue is timing-sensitive
4. The minimum code change needed to close the leak
5. One focused check that proves the leak is fixed

## Important

- "Object storage ACLs are too broad" is not a sufficient answer unless you can prove it from the repo
- You must explain both the cache-key problem and the placement of the permission check
