#!/usr/bin/env python3
"""Smoke test: verify llm_query works inside the Docker REPL (system / wiring check)."""

import json
import subprocess
import sys
from pathlib import Path


def load_config():
    config_path = Path("config.json")
    if not config_path.exists():
        print(f"Error: config.json not found at {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        return json.load(f)


def get_test_code(use_glm: bool, model: str):
    return f"""
# Test 1: Check that llm_query is available
print("=== Test 1: Checking llm_query availability ===")
print(f"llm_query function: {{llm_query}}")
print(f"Type: {{type(llm_query)}}")

# Test 2: Check environment variables
print("\\n=== Test 2: Environment variables ===")
import os
print(f"RLM_MODEL: {{os.environ.get('RLM_MODEL', 'NOT SET')}}")
print(f"USE_GLM: {{os.environ.get('USE_GLM', 'NOT SET')}}")
print(f"ZAI_API_BASE: {{os.environ.get('ZAI_API_BASE', 'NOT SET')}}")
print(f"ZAI_API_KEY present: {{bool(os.environ.get('ZAI_API_KEY'))}}")

# Test 3: Get a small chunk
print("\\n=== Test 3: Getting content chunk ===")
chunk_size = 500
chunk = content[:chunk_size]
print(f"Content length: {{len(content)}}")
print(f"Chunk size: {{len(chunk)}}")
print(f"First 100 chars of chunk: {{repr(chunk[:100])}}")

# Test 4: Call llm_query
print("\\n=== Test 4: Calling llm_query ===")
instruction = "Extract the main topic of this text in one sentence"
print(f"Instruction: {{instruction}}")

try:
    result = llm_query(chunk, instruction, model="{model}")
    print(f"\\nResult: {{result}}")
    print(f"Result length: {{len(result)}}")
except Exception as e:
    print(f"Error: {{e}}")
    import traceback
    traceback.print_exc()
"""


def run_test():
    """Run the test code in the Docker REPL."""
    config = load_config()

    print("Loaded config.json:")
    print(f"  GLM enabled: {config['glm_coding']['enabled']}")
    print(f"  Root model: {config['root_llm']['model']}")
    print(f"  Sub model: {config['sub_llm']['model']}")

    use_glm = config["glm_coding"]["enabled"]
    if use_glm:
        model = config["glm_coding"]["sub_model"]
        api_base = config["glm_coding"]["api_base"]
        print(f"  Using GLM coding API: {model}")
        print(f"  API base: {api_base}")
    else:
        model = config["sub_llm"]["model"]
        print(f"  Using standard model: {model}")

    env_file = Path(".env")
    workspace = Path(".rlm_state")

    if not env_file.exists():
        print(f"\nError: .env file not found at {env_file}")
        print("Please create a .env file with your API keys (ZAI_API_KEY for GLM).")
        sys.exit(1)

    if not workspace.exists():
        print(f"\nError: Workspace not found at {workspace}")
        print("Please run: uv run python main.py init <context_file>")
        sys.exit(1)

    extra_env = {"RLM_MODEL": model}
    if use_glm:
        extra_env["USE_GLM"] = "true"
        extra_env["ZAI_API_BASE"] = api_base

    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--env-file",
        str(env_file),
    ]
    for k, v in extra_env.items():
        cmd.extend(["-e", f"{k}={v}"])

    cmd.extend(
        [
            "-v",
            f"{workspace.absolute()}:/workspace",
            "-v",
            f"{env_file.absolute()}:/app/.env",
            "-w",
            "/workspace",
            "rlm-repl:latest",
            "exec",
        ]
    )

    print("\nRunning test with Docker command...")
    print(f"Workspace: {workspace}")
    print(f"Env file: {env_file}")
    print(f"Extra env vars: {extra_env}")
    print("-" * 60)

    test_code = get_test_code(use_glm, model)

    result = subprocess.run(
        cmd,
        input=test_code,
        capture_output=True,
        text=True,
    )

    print("STDOUT:")
    print(result.stdout)

    if result.stderr:
        print("\nSTDERR:")
        print(result.stderr)

    print(f"\nExit code: {result.returncode}")

    return result.returncode == 0


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)


