# Codebase Overview

High-level overview of how the RLM components interact to enable large-context reasoning through a sandboxed Python REPL.

## Project Structure

```text
├── rlm/
│   ├── cli/                # CLI interface (Click-based)
│   ├── config/             # Configuration loading and validation
│   ├── orchestrator/       # Core reasoning logic
│   │   ├── tools/          # Docker runner
│   │   ├── memory_compaction.py
│   │   ├── orchestrator.py
│   │   └── prompt.txt      # System prompt for root LLM
│   ├── repl/
│   │   └── rlm_repl.py     # Persistent REPL (runs inside Docker)
│   └── utils/              # Console output helpers
├── docker/                 # Dockerfile for the REPL sandbox
├── main.py                 # Entry point
└── config.json             # Model and feature configuration
```

## REPL Engine (`rlm/repl/rlm_repl.py`)

The execution engine. Stateful across invocations via pickle (`state.pkl`).

**Helpers injected into the execution environment:**
- `peek(start, end)` — slice the active file's content
- `grep(pattern)` — regex search with context windows
- `chunk_indices(size, overlap)` — get chunk boundaries for iteration
- `add_buffer(text)` — store intermediate results across calls
- `load_file`, `load_files`, `switch_to`, `list_files`, `remove_file` — context file management
- `llm_query(chunk, instruction)` — delegate a chunk to a sub-LLM for semantic analysis
- `FINAL(answer)`, `FINAL_VAR(variable)` — deliver the final answer directly from the REPL

## Docker Sandbox (`docker/`)

All REPL code executes inside an isolated Docker container.
- Minimal image: `python:3.12-slim` with `litellm` and `python-dotenv`
- State directory (`.rlm_state/`) and data files are volume-mounted at runtime
- API keys passed via `--env-file` and `-e` flags

## Orchestrator (`rlm/orchestrator/`)

The core reasoning loop.

**`orchestrator.py`** — main loop:
1. Sends user query + message history to the root LLM with the `run_repl` tool definition
2. When the LLM returns a tool call, extracts Python code and executes it in Docker
3. Feeds results back as tool messages
4. Loops until the LLM gives a final answer or `FINAL()` is called from the REPL
5. Optionally runs memory compaction after each interaction

**`prompt.txt`** — system prompt that teaches the root LLM the RLM pattern: how to use REPL helpers, chunking strategies, sub-LLM delegation, and `FINAL()` delivery.

**`memory_compaction.py`** — summarizes multi-turn tool-call histories into a compact message to prevent context window bloat.

**`tools/docker_runner.py`** — abstracts Docker CLI operations: image building, volume mounting, code execution, and state management.

## CLI (`rlm/cli/cli.py`)

Click-based interface with four commands: `init`, `chat`, `run`, `status`. Supports CLI overrides for models (`--model`, `--subllm`) and memory compaction (`--compact/--no-compact`).
