#!/usr/bin/env python3
"""Persistent mini-REPL for RLM-style workflows.

This script provides a *stateful* Python environment across invocations by
saving a pickle file to disk. It is intentionally small and dependency-free.

Typical flow:
  1) Initialise context:
       python rlm_repl.py init path/to/context.txt
  2) Execute code repeatedly (state persists):
       python rlm_repl.py exec -c 'print(len(content))'
       python rlm_repl.py exec <<'PYCODE'
       # you can write multi-line code
       hits = grep('TODO')
       print(hits[:3])
       PYCODE

The script injects these variables into the exec environment:
  - context: dict with keys {path, loaded_at, content}
  - content: string alias for context['content']
  - buffers: list[str] for storing intermediate text results

It also injects helpers:
  - peek(start=0, end=1000) -> str
  - grep(pattern, max_matches=20, window=120, flags=0) -> list[dict]
  - chunk_indices(size=200000, overlap=0) -> list[(start,end)]
  - write_chunks(out_dir, size=200000, overlap=0, prefix='chunk') -> list[str]
  - add_buffer(text: str) -> None

Security note:
  This runs arbitrary Python via exec. Treat it like running code you wrote.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import pickle
import re
import sys
import textwrap
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


DEFAULT_STATE_PATH = Path("state.pkl")
DEFAULT_MAX_OUTPUT_CHARS = 8000


class RlmReplError(RuntimeError):
    pass


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        raise RlmReplError(
            f"No state found at {state_path}. Run: python rlm_repl.py init <context_path>"
        )
    with state_path.open("rb") as f:
        state = pickle.load(f)
    if not isinstance(state, dict):
        raise RlmReplError(f"Corrupt state file: {state_path}")
    return state


def _save_state(state: Dict[str, Any], state_path: Path) -> None:
    _ensure_parent_dir(state_path)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with tmp_path.open("wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_path.replace(state_path)


def _read_text_file(path: Path, max_bytes: int | None = None) -> str:
    if not path.exists():
        raise RlmReplError(f"Context file does not exist: {path}")
    data: bytes
    with path.open("rb") as f:
        data = f.read() if max_bytes is None else f.read(max_bytes)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Fall back to a lossy decode that will not crash.
        return data.decode("utf-8", errors="replace")


def _truncate(s: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n... [truncated to {max_chars} chars] ...\n"


def _is_pickleable(value: Any) -> bool:
    try:
        pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        return True
    except Exception:
        return False


def _filter_pickleable(d: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    kept: Dict[str, Any] = {}
    dropped: List[str] = []
    for k, v in d.items():
        if _is_pickleable(v):
            kept[k] = v
        else:
            dropped.append(k)
    return kept, dropped


def _load_env_vars():
    """Load environment variables from .env if it exists.
    This is especially useful inside Docker to handle quoted strings.
    """
    import os
    from dotenv import load_dotenv
    # Load from /app/.env (where we will mount it) or current dir
    # We use override=True because Docker might have already loaded these 
    # but with literal quotes if they were quoted in the .env file.
    # python-dotenv handles the quotes correctly.
    if os.path.exists("/app/.env"):
        load_dotenv("/app/.env", override=True)
    load_dotenv(override=True)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _extract_usage_metrics(response) -> Dict[str, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None and hasattr(response, "model_dump"):
        usage = response.model_dump().get("usage")
    if usage is None:
        return {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }

    if hasattr(usage, "prompt_tokens"):
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
    else:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _safe_completion_cost(response) -> float | None:
    try:
        import litellm

        cost = litellm.completion_cost(completion_response=response)
    except Exception:
        return None
    return float(cost) if cost is not None else None


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True))
        handle.write("\n")


def _make_llm_query():
    """Create the llm_query helper that delegates chunk analysis to a sub-LLM."""
    import os
    import sys
    _load_env_vars()
    trace_sub_llm = os.environ.get("RLM_TRACE_SUB_LLM", "").lower() == "true"
    trace_path_env = os.environ.get("RLM_TRACE_SUB_LLM_PATH")
    trace_path = Path(trace_path_env) if trace_path_env else None

    def llm_query(
        chunk: str,
        instruction: str,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Delegate a sub-query to an LLM for chunk analysis.

        This is the core "Map" operation in the RLM pattern. Pass a chunk of
        text and an instruction, and the sub-LLM will extract/analyze/summarize
        the specific information you need.
        """
        import litellm

        model = model or os.environ.get("RLM_MODEL", "openai/gpt-4o-mini")
        prompt = f"{instruction}\n\n---\n\n{chunk}"
        started_at = _utc_now_iso()
        started_perf = time.perf_counter()

        try:
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            content = response.choices[0].message.content
            if trace_sub_llm and trace_path is not None:
                _append_jsonl(
                    trace_path,
                    {
                        "started_at": started_at,
                        "ended_at": _utc_now_iso(),
                        "latency_ms": (time.perf_counter() - started_perf) * 1000,
                        "model": model,
                        "usage": _extract_usage_metrics(response),
                        "context": {
                            "prompt_chars": len(prompt),
                            "prompt_messages": 1,
                            "context_window_tokens": None,
                            "context_window_pct": None,
                        },
                        "cost_usd": _safe_completion_cost(response),
                        "instruction_chars": len(instruction),
                        "chunk_chars": len(chunk),
                        "temperature": temperature,
                        "error": None,
                    },
                )
            return content
        except Exception as e:
            error_msg = f"[llm_query error: {type(e).__name__}: {str(e)}]"
            if trace_sub_llm and trace_path is not None:
                _append_jsonl(
                    trace_path,
                    {
                        "started_at": started_at,
                        "ended_at": _utc_now_iso(),
                        "latency_ms": (time.perf_counter() - started_perf) * 1000,
                        "model": model,
                        "usage": {
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "total_tokens": None,
                        },
                        "context": {
                            "prompt_chars": len(prompt),
                            "prompt_messages": 1,
                            "context_window_tokens": None,
                            "context_window_pct": None,
                        },
                        "cost_usd": None,
                        "instruction_chars": len(instruction),
                        "chunk_chars": len(chunk),
                        "temperature": temperature,
                        "error": error_msg,
                    },
                )
            print(error_msg, file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return error_msg

    return llm_query


def _make_final_helpers(state_path: Path):
    def FINAL(text: str) -> None:
        final_path = state_path.parent / "__rlm_final__.txt"
        final_path.write_text(str(text), encoding="utf-8")
        print(f"[FINAL] Answer set ({len(str(text))} chars)")

    def FINAL_VAR(variable: Any) -> None:
        FINAL(str(variable))

    return {
        "FINAL": FINAL,
        "FINAL_VAR": FINAL_VAR,
    }


def _make_helpers(files_ref: Dict[str, Any], state_ref: Dict[str, Any], buffers_ref: List[str], env_ref: Dict[str, Any]):
    # These close over files_ref/state_ref/buffers_ref so changes persist.
    def peek(start: int = 0, end: int = 1000) -> str:
        active = state_ref.get("active_file")
        if not active or active not in files_ref:
            return ""
        content = files_ref[active].get("content", "")
        return content[start:end]

    def grep(
        pattern: str,
        max_matches: int = 20,
        window: int = 120,
        flags: int = 0,
    ) -> List[Dict[str, Any]]:
        active = state_ref.get("active_file")
        if not active or active not in files_ref:
            return []
        content = files_ref[active].get("content", "")
        out: List[Dict[str, Any]] = []
        for m in re.finditer(pattern, content, flags):
            start, end = m.span()
            snippet_start = max(0, start - window)
            snippet_end = min(len(content), end + window)
            out.append(
                {
                    "match": m.group(0),
                    "span": (start, end),
                    "snippet": content[snippet_start:snippet_end],
                }
            )
            if len(out) >= max_matches:
                break
        return out

    def chunk_indices(size: int = 200_000, overlap: int = 0) -> List[Tuple[int, int]]:
        if size <= 0:
            raise ValueError("size must be > 0")
        if overlap < 0:
            raise ValueError("overlap must be >= 0")
        if overlap >= size:
            raise ValueError("overlap must be < size")

        active = state_ref.get("active_file")
        if not active or active not in files_ref:
            return []
        content = files_ref[active].get("content", "")
        n = len(content)
        spans: List[Tuple[int, int]] = []
        step = size - overlap
        for start in range(0, n, step):
            end = min(n, start + size)
            spans.append((start, end))
            if end >= n:
                break
        return spans

    def write_chunks(
        out_dir: str | os.PathLike,
        size: int = 200_000,
        overlap: int = 0,
        prefix: str = "chunk",
        encoding: str = "utf-8",
    ) -> List[str]:
        active = state_ref.get("active_file")
        if not active or active not in files_ref:
            return []
        content = files_ref[active].get("content", "")
        spans = chunk_indices(size=size, overlap=overlap)
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        paths: List[str] = []
        for i, (s, e) in enumerate(spans):
            p = out_path / f"{prefix}_{i:04d}.txt"
            p.write_text(content[s:e], encoding=encoding)
            paths.append(str(p))
        return paths

    def add_buffer(text: str) -> None:
        buffers_ref.append(str(text))

    def load_file(path: str | os.PathLike, name: str | None = None, replace_all: bool = False) -> str:
        """Load a new context file, replacing current content or adding to files."""
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        if replace_all:
            files_ref.clear()
            
        file_content = _read_text_file(path_obj)
        if name is None:
            name = path_obj.stem
            
        files_ref[name] = {
            "path": str(path_obj),
            "loaded_at": time.time(),
            "content": file_content
        }
        state_ref["active_file"] = name
        # Update the content and context aliases in the execution environment
        env_ref["content"] = file_content
        env_ref["context"] = files_ref[name]
        return f"Loaded {path} as '{name}' ({len(file_content):,} chars). Active file: {name}"

    def load_files(paths: List[str] | Dict[str, str], replace_all: bool = False) -> str:
        """Load multiple context files at once."""
        if replace_all:
            files_ref.clear()
            
        results = []
        last_name = None
        
        if isinstance(paths, dict):
            for name, path in paths.items():
                res = load_file(path, name=name)
                results.append(res)
                last_name = name
        else:
            for path in paths:
                res = load_file(path)
                results.append(res)
                last_name = Path(path).stem
        
        if last_name:
            state_ref["active_file"] = last_name
            
        return "\n".join(results)

    def switch_to(name: str) -> str:
        """Switch the active context file."""
        if name not in files_ref:
            raise KeyError(f"File '{name}' not found. Loaded files: {list(files_ref.keys())}")
        state_ref["active_file"] = name
        # Update the content and context aliases in the execution environment
        env_ref["content"] = files_ref[name].get("content", "")
        env_ref["context"] = files_ref[name]
        return f"Switched active file to '{name}'"

    def list_files() -> Dict[str, Any]:
        """List all loaded context files."""
        return {
            name: {
                "path": info["path"],
                "chars": len(info["content"]),
                "active": name == state_ref.get("active_file")
            }
            for name, info in files_ref.items()
        }

    def remove_file(name: str) -> str:
        """Remove a context file from memory."""
        if name not in files_ref:
            return f"File '{name}' not found."
        if name == state_ref.get("active_file"):
            return f"Cannot remove active file '{name}'. Switch to another file first."
        del files_ref[name]
        return f"Removed file '{name}'"

    return {
        "peek": peek,
        "grep": grep,
        "chunk_indices": chunk_indices,
        "write_chunks": write_chunks,
        "add_buffer": add_buffer,
        "load_file": load_file,
        "load_files": load_files,
        "switch_to": switch_to,
        "list_files": list_files,
        "remove_file": remove_file,
    }


def cmd_init(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    ctx_path = Path(args.context)

    content = _read_text_file(ctx_path, max_bytes=args.max_bytes)
    filename = ctx_path.stem
    state: Dict[str, Any] = {
        "files": {
            filename: {
                "path": str(ctx_path),
                "loaded_at": time.time(),
                "content": content,
            }
        },
        "active_file": filename,
        "buffers": [],
        "globals": {},
    }
    _save_state(state, state_path)

    print(f"Initialised RLM REPL state at: {state_path}")
    print(f"Loaded context: {ctx_path} as '{filename}' ({len(content):,} chars)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.state))
    files = state.get("files", {})
    active_file = state.get("active_file")
    buffers = state.get("buffers", [])
    g = state.get("globals", {})

    print("RLM REPL status")
    print(f"  State file: {args.state}")
    print(f"  Loaded files: {len(files)}")
    for name, info in files.items():
        marker = "*" if name == active_file else " "
        print(f"  {marker} {name}: {info.get('path')} ({len(info.get('content', '')):,} chars)")
    print(f"  Buffers: {len(buffers)}")
    print(f"  Persisted vars: {len(g)}")
    if args.show_vars and g:
        for k in sorted(g.keys()):
            print(f"    - {k}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    if state_path.exists():
        state_path.unlink()
        print(f"Deleted state: {state_path}")
    else:
        print(f"No state to delete at: {state_path}")
    return 0


def cmd_export_buffers(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.state))
    buffers = state.get("buffers", [])
    out_path = Path(args.out)
    _ensure_parent_dir(out_path)
    out_path.write_text("\n\n".join(str(b) for b in buffers), encoding="utf-8")
    print(f"Wrote {len(buffers)} buffers to: {out_path}")
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    
    # Handle empty state gracefully if it doesn't exist
    if not state_path.exists():
        state: Dict[str, Any] = {
            "files": {},
            "active_file": None,
            "buffers": [],
            "globals": {},
        }
        _save_state(state, state_path)
    else:
        state = _load_state(state_path)

    files = state.setdefault("files", {})
    active_file = state.get("active_file")
    
    buffers = state.setdefault("buffers", [])
    if not isinstance(buffers, list):
        buffers = []
        state["buffers"] = buffers

    persisted = state.setdefault("globals", {})
    if not isinstance(persisted, dict):
        persisted = {}
        state["globals"] = persisted

    code = args.code
    if code is None:
        code = sys.stdin.read()

    # Build execution environment.
    # Start from persisted variables, then inject context, buffers and helpers.
    env: Dict[str, Any] = dict(persisted)
    
    # Inject current active file info for backward compatibility
    if active_file and active_file in files:
        env["context"] = files[active_file]
        env["content"] = files[active_file].get("content", "")
    else:
        env["context"] = {}
        env["content"] = ""
        
    env["files"] = files
    env["buffers"] = buffers

    helpers = _make_helpers(files, state, buffers, env)
    final_helpers = _make_final_helpers(state_path)
    env["llm_query"] = _make_llm_query()
    env.update(helpers)
    env.update(final_helpers)

    # Capture output.
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, env, env)
    except Exception:
        traceback.print_exc(file=stderr_buf)

    # Pull back possibly mutated state.
    # helpers like load_file, switch_to, etc. mutate files/state/buffers in-place.
    
    # Persist any new variables, excluding injected keys.
    injected_keys = {
        "__builtins__",
        "context",
        "content",
        "files",
        "buffers",
        "llm_query",
        *helpers.keys(),
        *final_helpers.keys(),
    }
    to_persist = {k: v for k, v in env.items() if k not in injected_keys}
    filtered, dropped = _filter_pickleable(to_persist)
    state["globals"] = filtered

    _save_state(state, state_path)

    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()

    if dropped and args.warn_unpickleable:
        msg = "Dropped unpickleable variables: " + ", ".join(dropped)
        err = (err + ("\n" if err else "") + msg + "\n")

    if out:
        sys.stdout.write(_truncate(out, args.max_output_chars))

    if err:
        sys.stderr.write(_truncate(err, args.max_output_chars))

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rlm_repl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            Persistent mini-REPL for RLM-style workflows.

            Examples:
              python rlm_repl.py init context.txt
              python rlm_repl.py status
              python rlm_repl.py exec -c "print(len(content))"
              python rlm_repl.py exec <<'PY'
              print(peek(0, 2000))
              PY
            """
        ),
    )
    p.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help=f"Path to state pickle (default: {DEFAULT_STATE_PATH})",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialise state from a context file")
    p_init.add_argument("context", help="Path to the context file")
    p_init.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="Optional cap on bytes read from the context file",
    )
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="Show current state summary")
    p_status.add_argument(
        "--show-vars", action="store_true", help="List persisted variable names"
    )
    p_status.set_defaults(func=cmd_status)

    p_reset = sub.add_parser("reset", help="Delete the current state file")
    p_reset.set_defaults(func=cmd_reset)

    p_export = sub.add_parser(
        "export-buffers", help="Export buffers list to a text file"
    )
    p_export.add_argument("out", help="Output file path")
    p_export.set_defaults(func=cmd_export_buffers)

    p_exec = sub.add_parser("exec", help="Execute Python code with persisted state")
    p_exec.add_argument(
        "-c",
        "--code",
        default=None,
        help="Inline code string. If omitted, reads code from stdin.",
    )
    p_exec.add_argument(
        "--max-output-chars",
        type=int,
        default=DEFAULT_MAX_OUTPUT_CHARS,
        help=f"Truncate stdout/stderr to this many characters (default: {DEFAULT_MAX_OUTPUT_CHARS})",
    )
    p_exec.add_argument(
        "--warn-unpickleable",
        action="store_true",
        help="Warn on stderr when variables could not be persisted",
    )
    p_exec.set_defaults(func=cmd_exec)

    return p


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.func(args))
    except RlmReplError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
