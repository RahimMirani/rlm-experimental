# Aster Billing Workspace

This directory contains a compact service workspace centered on code investigation and incident analysis.

## Purpose

The materials here are organized to support deep codebase inspection:

- navigate a medium-sized codebase instead of a single flat text blob
- preserve state across multiple searches and intermediate findings
- trace bugs across API, service, repository, job, and config layers
- separate the real root cause from plausible but incomplete explanations

## Layout

- `repo/` contains the application code
- `tasks/` contains investigation briefs
- `answers/` contains internal reference notes

## Working Notes

When using these materials for a live investigation:

- work from `repo/`
- pair it with one brief from `tasks/`
- keep `answers/` separate from the investigation flow

## Characteristics

This workspace is intentionally hostile to shallow search:

- some symptoms are described in `repo/docs/incidents.md`
- some existing checks cover only partial happy paths
- several functions are locally reasonable but wrong in combination
- at least one task has two plausible answers, but only one fully matches the evidence

## Suggested Response Format

Ask for a response with:

1. The exact root cause
2. The full code path involved
3. The specific files/functions that matter
4. A minimal fix
5. Any missing coverage or guardrail that would have caught it
