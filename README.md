# RLM — Recursive Language Model

![RLM Diagram](https://cdn-uploads.huggingface.co/production/uploads/65ca6f0098a46a56261ac3ac/VmsN4ynKs8DLGfDGhi1dz.png)

An implementation and rigorous benchmarking project for Recursive Language Models, based on the paper by [Alex L. Zhang, Tim Kraska & Omar Khattab](https://arxiv.org/abs/2512.24601). Built on the foundation of [@KillerShoaib__'s from-scratch implementation](https://github.com/KillerShoaib/RLM-From-Scratch).

**Goal:** Build a clean, production-grade RLM, then run apples-to-apples benchmarks against standard agent architectures (ReAct, RAG) to quantify real-world gains in context-rot resistance, accuracy, cost, and scalability.

## Table of Contents

- [What is RLM](#what-is-rlm)
- [How It Works](#how-it-works)
- [Key Features](#key-features)
- [Setup](#setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [Managing Context](#managing-context)
- [Project Structure](#project-structure)
- [Credits](#credits)

## What is RLM

The core idea: instead of stuffing a million-token document into an LLM's context window, treat the document as a **variable** inside a stateful Python REPL. The LLM never sees the full text — it writes code to programmatically explore it.

- A **root LLM** generates Python code to inspect, slice, search, chunk, and analyze the data
- The code executes in a **sandboxed REPL** (Docker container) with persistent state
- The LLM can delegate semantic analysis of individual chunks to a **sub-LLM** via `llm_query()`
- Results flow back to the root LLM, which decides whether to run more code or deliver a final answer
- The final answer can bypass the LLM's output token limit via `FINAL()`, delivered directly from the REPL

This keeps the LLM's prompt tiny while enabling reasoning over arbitrarily large inputs.

### Isn't this just tool calling with Python in a loop?

No. Key differences:

- The dataset is treated as a **variable**, not passed as context
- The LLM uses **code** (symbolic language) to spawn sub-agents — it doesn't call them as tools
- Output is **truncated** to prevent context rot — the LLM only sees what it asks to see
- `FINAL()` bypasses the output token limit entirely (tool responses normally flow back through the LLM)
- The LLM can **iteratively refine** its answer across REPL calls via recursion and persistent state

> The original author [Omar Khattab](https://x.com/lateinteraction) explained this distinction in detail in [this X thread](https://x.com/lateinteraction/status/2020215204945252429).

## How It Works

```
User Query → CLI → Orchestrator ←→ Root LLM (via LiteLLM)
                        ↕
               Docker Sandbox (REPL)
                        ↕
                  Sub-LLM (llm_query)
```

1. User submits a query via CLI
2. Orchestrator sends query + system prompt to the root LLM
3. Root LLM generates Python code as a `run_repl` tool call
4. Code executes inside a Docker container running the persistent REPL
5. REPL has helpers (`peek`, `grep`, `chunk_indices`, `llm_query`) and persistent state
6. Results flow back; the LLM decides to run more code or deliver an answer
7. Memory compaction (optional) summarizes the interaction to save tokens

## Key Features

- **Docker sandboxing** — all code runs in an isolated container, not on your host
- **Persistent REPL state** — variables, loaded files, and buffers survive across invocations (via pickle)
- **Memory compaction** — post-interaction summarization prevents context window bloat
- **Model-agnostic** — swap any LiteLLM-supported model (OpenAI, Anthropic, Gemini, etc.) via config
- **FINAL() bypass** — deliver arbitrarily long answers directly from the REPL

## Setup

### Prerequisites

- Python 3.12+
- Docker (must run without `sudo`)
- [`uv`](https://docs.astral.sh/uv/) package manager

### Install

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/RLM-From-Scratch.git
cd RLM-From-Scratch

# Copy env template and add your API keys
cp .env.example .env

# Install dependencies
uv sync
```

Add the API keys you need to `.env` depending on which models you plan to use (e.g., `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).

## Configuration

Edit `config.json` to set your models:

```json
{
  "root_llm": {
    "model": "openrouter/google/gemini-3-flash-preview"
  },
  "sub_llm": {
    "model": "openrouter/google/gemini-3-flash-preview"
  },
  "memory_compaction": {
    "enabled": true
  }
}
```

- **`root_llm.model`** — the primary model that orchestrates reasoning and writes Python code
- **`sub_llm.model`** — the model used for semantic chunk analysis (`llm_query`)
- **`memory_compaction.enabled`** — summarize tool-call histories after each interaction to save tokens

Models use [LiteLLM format](https://docs.litellm.ai/): `provider/model-name`. You can override models via CLI flags: `--model`, `--subllm`, `--compact/--no-compact`.

## Usage

### Initialize with a file (recommended for large files)

```bash
uv run main.py init /absolute/path/to/data/my_dataset.txt
uv run main.py chat
```

### Start chat directly

```bash
uv run main.py chat
```

Then ask: *"Load the file at /absolute/path/to/data/info.txt and tell me what's in it."*

### Single query

```bash
uv run main.py run "Analyze /absolute/path/to/data/logs.txt and find all error messages"
```

### Check REPL state

```bash
uv run main.py status
```

### Fresh start

```bash
rm -rf .rlm_state
```

## Managing Context

During a session, the root LLM manages context by writing Python code using these REPL helpers:

> **Important:** Use **absolute paths** when loading files — required for Docker volume mounting.

| Helper | What it does |
|--------|-------------|
| `load_file(path, name)` | Load a file into the REPL |
| `load_files(paths)` | Batch-load multiple files |
| `switch_to(name)` | Change the active file |
| `list_files()` | Show loaded files |
| `remove_file(name)` | Drop a file from memory |
| `peek(start, end)` | Slice the active file's content |
| `grep(pattern)` | Regex search with context windows |
| `chunk_indices(size, overlap)` | Get chunk boundaries for iteration |
| `llm_query(chunk, instruction)` | Delegate a chunk to the sub-LLM |
| `add_buffer(text)` | Store intermediate results |
| `FINAL(answer)` | Deliver the final answer from the REPL |

## Project Structure

```
├── main.py                      # Entry point
├── config.json                  # Model and feature configuration
├── strategy.md                  # Project roadmap and benchmarking plan
├── rlm/
│   ├── cli/cli.py               # Click-based CLI (init, chat, run, status)
│   ├── config/config.py         # Config loading and validation
│   ├── orchestrator/
│   │   ├── orchestrator.py      # Core reasoning loop (LLM ↔ REPL)
│   │   ├── memory_compaction.py # Post-interaction summarization
│   │   ├── prompt.txt           # System prompt for the root LLM
│   │   └── tools/docker_runner.py  # Docker CLI abstraction
│   ├── repl/rlm_repl.py        # Stateful Python REPL (runs in Docker)
│   └── utils/console.py        # Rich terminal output
├── docker/
│   ├── Dockerfile               # REPL container definition
│   └── .dockerignore
└── docs/
    └── codebase_overview.md     # Architecture documentation
```

See [`docs/codebase_overview.md`](docs/codebase_overview.md) for detailed architecture documentation.

## Credits

- **Original paper:** [Recursive Language Models](https://arxiv.org/abs/2512.24601) by Alex L. Zhang, Tim Kraska & Omar Khattab
- **Base implementation:** [@KillerShoaib__](https://github.com/KillerShoaib/RLM-From-Scratch)
- **REPL sandbox approach:** Inspired by [Brainqub3's video on RLMs with Claude Code](https://www.youtube.com/watch?v=m6itCxJFqpo)
