# Incident Brief 01: Duplicate Charge Root Cause

Work only from the repository in this workspace.

## Scenario

Operations reports incident `INC-1042`: some customers are charged twice after retrying checkout when the first attempt appears to hang.

## Request

Identify the real root cause of the duplicate-charge path.

Your answer must include:

1. The exact code path from API entrypoint to payment gateway call
2. Why the current retry behavior can create a second charge
3. Why the issue is not fully explained by a missing uniqueness constraint on `client_reference`
4. The smallest safe fix
5. One focused check that would have caught this

## Important

- A partial answer that only says "the API retries" is not enough
- You must explain what stable value should be reused across retries
