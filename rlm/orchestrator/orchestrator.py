import json
import logging
import os
from pathlib import Path
import litellm
from rlm.orchestrator.tools import docker_runner
from rlm.orchestrator.memory_compaction import MemoryCompactor
from rlm.utils import console
import re
logger = logging.getLogger(__name__)

def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return "You are an RLM (Reasoning Language Model) that analyzes large files through a Python REPL."

FINAL_ANSWER_FILENAME = "__rlm_final__.txt"

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

    def _get_extra_env_for_repl(self) -> dict:
        """Build environment variables to pass to REPL container."""
        extra_env = {"RLM_MODEL": self.sub_model}

        for k, v in os.environ.items():
            if k.startswith(("RLM_", "OPENAI_", "ANTHROPIC_", "AZURE_", "GEMINI_")):
                extra_env[k] = v

        return extra_env

    def run(self, user_query: str):
        interaction_start_idx = len(self.messages)

        self.messages.append({"role": "user", "content": user_query})

        while True:
            completion_kwargs = {
                "model": self.root_model,
                "messages": self.messages,
                "tools": [REPL_TOOL],
            }

            with console.get_status_spinner("Thinking...") as status:
                response = litellm.completion(**completion_kwargs)

            assistant_message = response.choices[0].message

            msg_dict = assistant_message.model_dump()
            if msg_dict.get("content") is None:
                msg_dict["content"] = ""
            self.messages.append(msg_dict)

            if not assistant_message.tool_calls:
                console.print_assistant_answer(assistant_message.content)

                if self.compact_enabled:
                    with console.get_status_spinner("Memory summarization...") as status:
                        messages_to_summarize = self.messages[interaction_start_idx:]
                        summary = self.compactor.summarize(messages_to_summarize)

                        self.messages = self.messages[:interaction_start_idx] + [
                            {"role": "system", "content": f"Previous interaction summary: {summary}"}
                        ]

                return assistant_message.content

            final_answer = None
            for tool_call in assistant_message.tool_calls:
                if tool_call.function.name == "run_repl":
                    try:
                        args = json.loads(tool_call.function.arguments)
                        python_code = args["python_code"]

                        console.print_tool_call(python_code)

                        current_mounts = self._extract_file_paths(python_code)
                        extra_env = self._get_extra_env_for_repl()

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
                        if final_path.exists():
                            final_answer = final_path.read_text(encoding="utf-8")
                            final_path.unlink()
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
