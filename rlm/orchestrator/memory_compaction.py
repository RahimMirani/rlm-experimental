import litellm
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class MemoryCompactor:
    def __init__(self, config: dict):
        self.config = config
        self.model = config["root_llm"]["model"]

    def summarize(self, messages_to_summarize: List[Dict]) -> str:
        """Summarize a sequence of messages into a concise description of what happened."""
        if not messages_to_summarize:
            return ""

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

        try:
            response = litellm.completion(
                model=self.model,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            summary = response.choices[0].message.content.strip()
            return summary
        except Exception as e:
            logger.error(f"Error during memory compaction: {e}")
            return "Error: Could not summarize this interaction."
