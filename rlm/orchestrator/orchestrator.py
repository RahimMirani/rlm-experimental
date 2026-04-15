import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
import litellm
from rlm.orchestrator.tools import docker_runner
from rlm.orchestrator.memory_compaction import MemoryCompactor
from rlm.tracing import (
    ContextWindowMetrics,
    JSONLTraceWriter,
    ReplExecEvent,
    RootLLMCallEvent,
    SubLLMCallEvent,
    RunOutcome,
    UsageMetrics,
    create_run_trace,
    utc_now,
)
from rlm.utils import console
import re
logger = logging.getLogger(__name__)

def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return "You are an RLM (Reasoning Language Model) that analyzes large files through a Python REPL."

FINAL_ANSWER_FILENAME = "__rlm_final__.txt"
SUB_LLM_TRACE_FILENAME_TEMPLATE = "sub-llm-events-{run_id}.jsonl"


def _message_content_chars(messages: list[dict]) -> int:
    return sum(len(str(message.get("content", ""))) for message in messages)


def _extract_usage_metrics(response) -> UsageMetrics:
    usage = getattr(response, "usage", None)
    if usage is None and hasattr(response, "model_dump"):
        usage = response.model_dump().get("usage")
    if usage is None:
        return UsageMetrics()

    if hasattr(usage, "prompt_tokens"):
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
    else:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

    return UsageMetrics(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _safe_completion_cost(response) -> float | None:
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:
        return None
    return float(cost) if cost is not None else None


def _update_root_totals(trace, usage: UsageMetrics, cost_usd: float | None) -> None:
    trace.totals.root_prompt_tokens += usage.prompt_tokens or 0
    trace.totals.root_completion_tokens += usage.completion_tokens or 0
    trace.totals.root_total_tokens += usage.total_tokens or 0
    trace.totals.total_cost_usd += cost_usd or 0.0


def _update_sub_totals(trace, usage: UsageMetrics, cost_usd: float | None) -> None:
    trace.totals.sub_prompt_tokens += usage.prompt_tokens or 0
    trace.totals.sub_completion_tokens += usage.completion_tokens or 0
    trace.totals.sub_total_tokens += usage.total_tokens or 0
    trace.totals.total_cost_usd += cost_usd or 0.0


def _parse_sub_llm_event(payload: dict, call_index: int) -> SubLLMCallEvent:
    usage_payload = payload.get("usage") or {}
    context_payload = payload.get("context") or {}
    return SubLLMCallEvent(
        call_index=call_index,
        started_at=datetime.fromisoformat(payload["started_at"]),
        ended_at=datetime.fromisoformat(payload["ended_at"]),
        latency_ms=payload.get("latency_ms", 0.0),
        model=payload.get("model", "unknown"),
        usage=UsageMetrics(
            prompt_tokens=usage_payload.get("prompt_tokens"),
            completion_tokens=usage_payload.get("completion_tokens"),
            total_tokens=usage_payload.get("total_tokens"),
        ),
        context=ContextWindowMetrics(
            prompt_chars=context_payload.get("prompt_chars"),
            prompt_messages=context_payload.get("prompt_messages"),
            context_window_tokens=context_payload.get("context_window_tokens"),
            context_window_pct=context_payload.get("context_window_pct"),
        ),
        cost_usd=payload.get("cost_usd"),
        instruction_chars=payload.get("instruction_chars"),
        chunk_chars=payload.get("chunk_chars"),
        temperature=payload.get("temperature"),
        error=payload.get("error"),
    )


def _ingest_sub_llm_events(trace, event_path: Path, consumed_lines: int) -> int:
    if not event_path.exists():
        return consumed_lines

    lines = event_path.read_text(encoding="utf-8").splitlines()
    for raw_line in lines[consumed_lines:]:
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed sub-LLM trace line")
            continue
        event = _parse_sub_llm_event(payload, len(trace.sub_llm_calls) + 1)
        trace.sub_llm_calls.append(event)
        _update_sub_totals(trace, event.usage, event.cost_usd)
    return len(lines)

REPL_TOOL = {
    "type": "function",
    "function": {
        "name": "run_repl",
        "description": """Execute Python code to search and explore the loaded context file.

The context file is already loaded (via init). Use this tool to search, slice, and analyze it.

Pre-loaded variables:
- content: str - The full text of the context file (search/slice it, e.g., content[0:5000])
- context: dict - Metadata {path, loaded_at, content}
- buffers: list - Accumulate intermediate results across calls
- Any variables you defined in previous calls

Search helpers:
- peek(start=0, end=1000) -> str: Slice content[start:end]
- grep(pattern, max_matches=20, window=120) -> list[dict]: Regex search with surrounding context
- chunk_indices(size=200000, overlap=0) -> list[tuple]: Get chunk boundaries for iteration
- add_buffer(text: str) -> None: Add a string to the global 'buffers' list.

Sub-query delegation:
- llm_query(chunk: str, instruction: str) -> str: Pass a chunk and instruction to extract semantic information

Final answer delivery:
- FINAL(answer: str) -> None: Deliver a string as the final answer directly from the REPL.
- FINAL_VAR(variable) -> None: Deliver a variable's string value as the final answer.

You can write any Python for searching: regex, string ops, loops over chunks, etc.""",
        "parameters": {
            "type": "object",
            "properties": {
                "python_code": {
                    "type": "string",
                    "description": "Python code to search/explore the content"
                }
            },
            "required": ["python_code"]
        }
    }
}

class Orchestrator:
    def __init__(self, config: dict, env_file: Path, workspace: Path):
        self.config = config
        self.env_file = env_file
        self.workspace = workspace
        self.root_model = config["root_llm"]["model"]
        self.sub_model = config["sub_llm"]["model"]
        self.system_prompt = load_system_prompt()
        self.messages: list[dict] = [{"role": "system", "content": self.system_prompt}]
        self.compactor = MemoryCompactor(config)
        self.compact_enabled = config["memory_compaction"]["enabled"]
        self.tracing_config = config["tracing"]
        self.tracing_enabled = self.tracing_config["enabled"]
        self.max_iterations = config["max_iterations"]
        self.trace_writer = (
            JSONLTraceWriter(self.tracing_config["log_dir"])
            if self.tracing_enabled
            else None
        )

        logger.info(
            f"Orchestrator initialized: root_model={self.root_model}, "
            f"sub_model={self.sub_model}"
        )

    def _extract_file_paths(self, code: str) -> list[Path]:
        """Extract absolute file paths from the code block if loading helpers are used."""
        if "load_file" not in code and "load_files" not in code:
            return []

        paths = []
        potential_paths = re.findall(r'["\'](([A-Za-z]:\\[^"\']+)|(/[^"\']+))["\']', code)
        for match in potential_paths:
            p = match[0]
            if len(p) > 2:
                paths.append(Path(p))
        return paths

    def _get_extra_env_for_repl(self, trace=None) -> dict:
        """Build environment variables to pass to REPL container."""
        extra_env = {"RLM_MODEL": self.sub_model}
        if (
            trace is not None
            and self.tracing_enabled
            and self.tracing_config["capture_sub_llm"]
        ):
            extra_env["RLM_TRACE_SUB_LLM"] = "true"
            extra_env["RLM_TRACE_SUB_LLM_PATH"] = (
                f"/workspace/{SUB_LLM_TRACE_FILENAME_TEMPLATE.format(run_id=trace.metadata.run_id)}"
            )

        for k, v in os.environ.items():
            if k.startswith(("RLM_", "OPENAI_", "ANTHROPIC_", "AZURE_", "GEMINI_")):
                extra_env[k] = v

        return extra_env

    def run(self, user_query: str):
        trace = (
            create_run_trace(
                query=user_query,
                root_model=self.root_model,
                sub_model=self.sub_model,
            )
            if self.tracing_enabled
            else None
        )
        run_started_perf = time.perf_counter()
        interaction_start_idx = len(self.messages)
        final_answer_path = None
        final_answer = None
        iteration_count = 0
        sub_llm_event_lines = 0
        sub_llm_trace_path = None

        self.messages.append({"role": "user", "content": user_query})
        if trace is not None and self.tracing_config["capture_sub_llm"]:
            sub_llm_trace_path = self.workspace / SUB_LLM_TRACE_FILENAME_TEMPLATE.format(
                run_id=trace.metadata.run_id
            )
            if sub_llm_trace_path.exists():
                sub_llm_trace_path.unlink()

        try:
            while True:
                iteration_count += 1
                if iteration_count > self.max_iterations:
                    raise RuntimeError(
                        f"Max iterations reached ({self.max_iterations}) before producing a final answer"
                    )

                call_index = len(trace.root_calls) + 1 if trace is not None else iteration_count
                root_started_at = utc_now()
                root_started_perf = time.perf_counter()
                completion_kwargs = {
                    "model": self.root_model,
                    "messages": self.messages,
                    "tools": [REPL_TOOL],
                }

                with console.get_status_spinner("Thinking...") as status:
                    response = litellm.completion(**completion_kwargs)

                root_ended_at = utc_now()
                usage = _extract_usage_metrics(response)
                cost_usd = _safe_completion_cost(response)
                assistant_message = response.choices[0].message
                if trace is not None:
                    root_event = RootLLMCallEvent(
                        call_index=call_index,
                        started_at=root_started_at,
                        ended_at=root_ended_at,
                        latency_ms=(time.perf_counter() - root_started_perf) * 1000,
                        model=self.root_model,
                        usage=usage,
                        context=ContextWindowMetrics(
                            prompt_chars=_message_content_chars(self.messages),
                            prompt_messages=len(self.messages),
                        ),
                        cost_usd=cost_usd,
                        message_count=len(self.messages),
                        tool_call_count=len(assistant_message.tool_calls or []),
                        assistant_content_chars=len(assistant_message.content or ""),
                        finish_reason=getattr(response.choices[0], "finish_reason", None),
                    )
                    trace.root_calls.append(root_event)
                    _update_root_totals(trace, usage, cost_usd)

                msg_dict = assistant_message.model_dump()
                if msg_dict.get("content") is None:
                    msg_dict["content"] = ""
                self.messages.append(msg_dict)

                if not assistant_message.tool_calls:
                    console.print_assistant_answer(assistant_message.content)
                    final_answer = assistant_message.content
                    final_answer_path = "assistant_direct"

                    if self.compact_enabled:
                        with console.get_status_spinner("Memory summarization...") as status:
                            messages_to_summarize = self.messages[interaction_start_idx:]
                            summary = self.compactor.summarize(messages_to_summarize)

                            self.messages = self.messages[:interaction_start_idx] + [
                                {"role": "system", "content": f"Previous interaction summary: {summary}"}
                            ]

                    return final_answer

                for tool_call in assistant_message.tool_calls:
                    if tool_call.function.name == "run_repl":
                        repl_started_at = utc_now()
                        repl_started_perf = time.perf_counter()
                        python_code = ""
                        current_mounts = []
                        try:
                            args = json.loads(tool_call.function.arguments)
                            python_code = args["python_code"]

                            console.print_tool_call(python_code)

                            current_mounts = self._extract_file_paths(python_code)
                            extra_env = self._get_extra_env_for_repl(trace)

                            with console.get_status_spinner("Executing REPL...") as status:
                                stdout, stderr, exit_code = docker_runner.run_exec(
                                    code=python_code,
                                    state_dir=self.workspace,
                                    env_file=self.env_file,
                                    extra_env=extra_env,
                                    mount_paths=current_mounts
                                )

                            result = stdout
                            if stderr:
                                result += f"\n[stderr]: {stderr}"
                            if exit_code != 0:
                                result += f"\n[exit_code]: {exit_code}"

                            console.print_tool_result(result)

                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": result
                            })

                            final_path = self.workspace / FINAL_ANSWER_FILENAME
                            if trace is not None:
                                repl_event = ReplExecEvent(
                                    exec_index=len(trace.repl_execs) + 1,
                                    started_at=repl_started_at,
                                    ended_at=utc_now(),
                                    latency_ms=(time.perf_counter() - repl_started_perf) * 1000,
                                    python_code_chars=len(python_code),
                                    mounted_paths=[str(path) for path in current_mounts],
                                    exit_code=exit_code,
                                    stdout_chars=len(stdout),
                                    stderr_chars=len(stderr),
                                    final_answer_emitted=final_path.exists(),
                                    tool_call_id=tool_call.id,
                                )
                                trace.repl_execs.append(repl_event)
                                if sub_llm_trace_path is not None:
                                    sub_llm_event_lines = _ingest_sub_llm_events(
                                        trace,
                                        sub_llm_trace_path,
                                        sub_llm_event_lines,
                                    )

                            if final_path.exists():
                                final_answer = final_path.read_text(encoding="utf-8")
                                final_path.unlink()
                                final_answer_path = "repl_final"
                                console.print_final_answer(final_answer)
                                break

                        except Exception as e:
                            error_msg = f"Error executing tool: {str(e)}"
                            console.print_tool_result(error_msg)
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": error_msg
                            })
                            if trace is not None:
                                trace.repl_execs.append(
                                    ReplExecEvent(
                                        exec_index=len(trace.repl_execs) + 1,
                                        started_at=repl_started_at,
                                        ended_at=utc_now(),
                                        latency_ms=(time.perf_counter() - repl_started_perf) * 1000,
                                        python_code_chars=len(python_code),
                                        mounted_paths=[str(path) for path in current_mounts],
                                        exit_code=None,
                                        stdout_chars=0,
                                        stderr_chars=len(error_msg),
                                        final_answer_emitted=False,
                                        tool_call_id=tool_call.id,
                                    )
                                )
                                if sub_llm_trace_path is not None:
                                    sub_llm_event_lines = _ingest_sub_llm_events(
                                        trace,
                                        sub_llm_trace_path,
                                        sub_llm_event_lines,
                                    )
                    else:
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"Unknown tool: {tool_call.function.name}"
                        })

                if final_answer is not None:
                    truncated_ans = final_answer[:2000] + "..." if len(final_answer) > 2000 else final_answer
                    note = f"\n\nThe final answer was delivered directly from the REPL. First 2000 chars: {truncated_ans}"

                    if self.compact_enabled:
                        with console.get_status_spinner("Memory summarization...") as status:
                            messages_to_summarize = self.messages[interaction_start_idx:]
                            summary = self.compactor.summarize(messages_to_summarize)

                            self.messages = self.messages[:interaction_start_idx] + [
                                {"role": "system", "content": f"Previous interaction summary: {summary}{note}"}
                            ]
                    else:
                        self.messages.append({
                            "role": "system",
                            "content": f"Interaction complete. {note}"
                        })

                    return final_answer
        except Exception as exc:
            if trace is not None:
                trace.outcome = RunOutcome(
                    status="error",
                    ended_at=utc_now(),
                    duration_ms=(time.perf_counter() - run_started_perf) * 1000,
                    final_answer_path=final_answer_path,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    root_iterations=len(trace.root_calls),
                    repl_exec_count=len(trace.repl_execs),
                )
            raise
        finally:
            if trace is not None:
                if sub_llm_trace_path is not None:
                    _ingest_sub_llm_events(trace, sub_llm_trace_path, sub_llm_event_lines)
                if trace.outcome is None:
                    trace.outcome = RunOutcome(
                        status="success",
                        ended_at=utc_now(),
                        duration_ms=(time.perf_counter() - run_started_perf) * 1000,
                        final_answer_path=final_answer_path,
                        root_iterations=len(trace.root_calls),
                        repl_exec_count=len(trace.repl_execs),
                    )
                self.trace_writer.append(trace)
