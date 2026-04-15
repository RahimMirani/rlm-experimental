import litellm
import logging
import time
from typing import List, Dict
from rlm.tracing import ContextWindowMetrics, MemoryCompactionCallEvent, UsageMetrics, utc_now

logger = logging.getLogger(__name__)


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

class MemoryCompactor:
    def __init__(self, config: dict):
        self.config = config
        self.model = config["root_llm"]["model"]

    def summarize(self, messages_to_summarize: List[Dict]) -> str:
        summary, _ = self.summarize_with_event(messages_to_summarize)
        return summary

    def summarize_with_event(self, messages_to_summarize: List[Dict]) -> tuple[str, MemoryCompactionCallEvent | None]:
        """Summarize a sequence of messages into a concise description of what happened."""
        if not messages_to_summarize:
            return "", None

        summary_prompt = (
            "You are a memory compaction assistant. Your task is to summarize the following "
            "interaction between a user and an AI assistant (which uses a Python REPL for data analysis). "
            "The summary should be concise but capture:\n"
            "1. The user's original request.\n"
            "2. The key actions taken in the REPL (what was searched or analyzed).\n"
            "3. The final conclusion or answer provided.\n\n"
            "Interaction to summarize:\n"
        )

        for msg in messages_to_summarize:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    content += f"\n[Tool Call: {tc['function']['name']}({tc['function']['arguments']})]"
            summary_prompt += f"--- {role} ---\n{content}\n"

        summary_prompt += "\nProvide a 2-3 sentence summary of this interaction:"

        started_at = utc_now()
        started_perf = time.perf_counter()
        try:
            response = litellm.completion(
                model=self.model,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            summary = response.choices[0].message.content.strip()
            event = MemoryCompactionCallEvent(
                started_at=started_at,
                ended_at=utc_now(),
                latency_ms=(time.perf_counter() - started_perf) * 1000,
                model=self.model,
                usage=_extract_usage_metrics(response),
                context=ContextWindowMetrics(
                    prompt_chars=len(summary_prompt),
                    prompt_messages=1,
                ),
                cost_usd=_safe_completion_cost(response),
                input_message_count=len(messages_to_summarize),
                output_message_count=1,
                summary_chars=len(summary),
            )
            return summary, event
        except Exception as e:
            logger.error(f"Error during memory compaction: {e}")
            event = MemoryCompactionCallEvent(
                started_at=started_at,
                ended_at=utc_now(),
                latency_ms=(time.perf_counter() - started_perf) * 1000,
                model=self.model,
                usage=UsageMetrics(),
                context=ContextWindowMetrics(
                    prompt_chars=len(summary_prompt),
                    prompt_messages=1,
                ),
                cost_usd=None,
                input_message_count=len(messages_to_summarize),
                output_message_count=1,
                summary_chars=len("Error: Could not summarize this interaction."),
            )
            return "Error: Could not summarize this interaction.", event
