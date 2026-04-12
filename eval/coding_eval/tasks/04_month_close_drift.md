# Incident Brief 04: Scheduled Close vs Manual Rebuild Drift

Work only from the repository in this workspace.

## Scenario

Finance reports incident `INC-1299`: a manual month rebuild for a tenant can disagree with the scheduled month-close for the same month.

## Request

Determine the actual reason the two paths diverge.

Your answer must include:

1. The exact code path for the scheduled close
2. The exact code path for the manual rebuild
3. The semantic difference between the two paths
4. Why the discrepancy clusters near month boundaries
5. The minimum code change that aligns behavior with stated finance policy

## Important

- A vague answer about timezones is not enough
- You must identify which timestamp field each path uses and why that matters
