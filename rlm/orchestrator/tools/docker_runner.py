import subprocess
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

IMAGE_NAME = "rlm-repl:latest"

def build_image(dockerfile_path: Path, root_dir: Path):
    """Build the Docker image if it doesn't exist."""
    try:
        # Check if image exists
        result = subprocess.run(
            ["docker", "image", "inspect", IMAGE_NAME],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info(f"Docker image {IMAGE_NAME} already exists.")
            return

        logger.info(f"Building Docker image {IMAGE_NAME}...")
        subprocess.run(
            ["docker", "build", "-t", IMAGE_NAME, "-f", str(dockerfile_path), str(root_dir)],
            check=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to build Docker image: {e}")
        raise

def run_init(context_path: Path, state_dir: Path, env_file: Path) -> tuple[str, str, int]:
    """Initialize REPL with a context file."""
    # Ensure state_dir is absolute for Docker mounting
    state_dir = state_dir.absolute()
    context_path = context_path.absolute()
    
    # We need to mount the context file as well, or copy it to state_dir
    # For simplicity, let's assume the context file is reachable or we mount its parent
    context_parent = context_path.parent
    
    cmd = [
        "docker", "run", "--rm",
        "--env-file", str(env_file),
        "-v", f"{state_dir}:/workspace",
        "-v", f"{context_parent}:{context_parent}",
        "-w", "/workspace",
        IMAGE_NAME,
        "init", str(context_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def run_exec(code: str, state_dir: Path, env_file: Path, extra_env: dict[str, str] | None = None, mount_paths: list[Path] | None = None) -> tuple[str, str, int]:
    """Execute Python code in the sandboxed REPL."""
    state_dir = state_dir.absolute()
    env_file = env_file.absolute()
    
    cmd = [
        "docker", "run", "--rm", "-i",
        "--env-file", str(env_file),
    ]
    
    if extra_env:
        for k, v in extra_env.items():
            cmd.extend(["-e", f"{k}={v}"])
            
    cmd.extend([
        "-v", f"{state_dir}:/workspace",
        "-v", f"{env_file}:/app/.env",
    ])

    if mount_paths:
        for p in mount_paths:
            p = p.absolute()
            if p.is_file():
                parent = p.parent
                cmd.extend(["-v", f"{parent}:{parent}"])
            elif p.is_dir():
                cmd.extend(["-v", f"{p}:{p}"])

    cmd.extend([
        "-w", "/workspace",
        IMAGE_NAME,
        "exec"
    ])
    
    result = subprocess.run(cmd, input=code, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def run_status(state_dir: Path, env_file: Path) -> tuple[str, str, int]:
    """Get current REPL state summary."""
    state_dir = state_dir.absolute()
    
    cmd = [
        "docker", "run", "--rm",
        "--env-file", str(env_file),
        "-v", f"{state_dir}:/workspace",
        "-w", "/workspace",
        IMAGE_NAME,
        "status"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode
