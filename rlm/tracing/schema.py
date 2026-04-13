from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def new_run_id() -> str:
    """Generate a unique identifier for one top-level trace."""
    return uuid4().hex


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


@dataclass(slots=True)
class UsageMetrics:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class ContextWindowMetrics:
    prompt_chars: int | None = None
    prompt_messages: int | None = None
    context_window_tokens: int | None = None
    context_window_pct: float | None = None


@dataclass(slots=True)
class RunMetadata:
    run_id: str
    query: str
    root_model: str
    sub_model: str
    tracing_version: str = "1"
    started_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class RootLLMCallEvent:
    call_index: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    model: str
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    context: ContextWindowMetrics = field(default_factory=ContextWindowMetrics)
    cost_usd: float | None = None
    message_count: int | None = None
    tool_call_count: int | None = None
    assistant_content_chars: int | None = None
    finish_reason: str | None = None


@dataclass(slots=True)
class ReplExecEvent:
    exec_index: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    python_code_chars: int
    mounted_paths: list[str] = field(default_factory=list)
    exit_code: int | None = None
    stdout_chars: int | None = None
    stderr_chars: int | None = None
    final_answer_emitted: bool = False
    tool_call_id: str | None = None


@dataclass(slots=True)
class SubLLMCallEvent:
    call_index: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    model: str
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    context: ContextWindowMetrics = field(default_factory=ContextWindowMetrics)
    cost_usd: float | None = None
    instruction_chars: int | None = None
    chunk_chars: int | None = None
    temperature: float | None = None
    error: str | None = None


@dataclass(slots=True)
class MemoryCompactionCallEvent:
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    model: str
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    context: ContextWindowMetrics = field(default_factory=ContextWindowMetrics)
    cost_usd: float | None = None
    input_message_count: int | None = None
    summary_chars: int | None = None


@dataclass(slots=True)
class StateSnapshotEvent:
    snapshot_index: int
    recorded_at: datetime
    active_file: str | None = None
    loaded_file_count: int = 0
    loaded_file_chars: dict[str, int] = field(default_factory=dict)
    total_loaded_chars: int = 0
    buffer_count: int = 0
    total_buffer_chars: int = 0
    persisted_globals_count: int = 0


@dataclass(slots=True)
class RunOutcome:
    status: str
    ended_at: datetime
    duration_ms: float
    final_answer_path: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    root_iterations: int | None = None
    repl_exec_count: int | None = None


@dataclass(slots=True)
class RunTotals:
    root_prompt_tokens: int = 0
    root_completion_tokens: int = 0
    root_total_tokens: int = 0
    sub_prompt_tokens: int = 0
    sub_completion_tokens: int = 0
    sub_total_tokens: int = 0
    compaction_prompt_tokens: int = 0
    compaction_completion_tokens: int = 0
    compaction_total_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass(slots=True)
class RunTrace:
    metadata: RunMetadata
    totals: RunTotals = field(default_factory=RunTotals)
    root_calls: list[RootLLMCallEvent] = field(default_factory=list)
    repl_execs: list[ReplExecEvent] = field(default_factory=list)
    sub_llm_calls: list[SubLLMCallEvent] = field(default_factory=list)
    state_snapshots: list[StateSnapshotEvent] = field(default_factory=list)
    compaction_calls: list[MemoryCompactionCallEvent] = field(default_factory=list)
    outcome: RunOutcome | None = None

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


def create_run_trace(query: str, root_model: str, sub_model: str) -> RunTrace:
    return RunTrace(
        metadata=RunMetadata(
            run_id=new_run_id(),
            query=query,
            root_model=root_model,
            sub_model=sub_model,
        )
    )
