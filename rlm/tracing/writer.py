from __future__ import annotations

import json
from pathlib import Path

from rlm.tracing.schema import RunTrace


DEFAULT_TRACE_DIR = Path("logs/traces")


class JSONLTraceWriter:
    """Append one structured run trace per line."""

    def __init__(self, log_dir: Path | str = DEFAULT_TRACE_DIR):
        self.log_dir = Path(log_dir)

    def trace_path_for(self, trace: RunTrace) -> Path:
        day = trace.metadata.started_at.strftime("%Y-%m-%d")
        return self.log_dir / f"runs-{day}.jsonl"

    def append(self, trace: RunTrace) -> Path:
        path = self.trace_path_for(trace)
        path.parent.mkdir(parents=True, exist_ok=True)

        line = json.dumps(trace.to_dict(), ensure_ascii=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")

        return path
