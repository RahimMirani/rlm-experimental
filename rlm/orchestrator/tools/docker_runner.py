import subprocess
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

IMAGE_NAME = "rlm-repl:latest"
CONTAINER_INPUT_ROOT = "/input"
CONTAINER_MOUNT_ROOT = "/host_mounts"


def _add_bind_mount(cmd: list[str], source: Path, target: str) -> None:
    """Add a Docker bind mount using --mount for Windows-safe path handling."""
    cmd.extend([
        "--mount",
        f"type=bind,source={source.resolve()},target={target}"
    ])


def _container_child_path(parent: str, child_name: str) -> str:
    return f"{parent.rstrip('/')}/{child_name}"


def _mount_target_for_index(index: int) -> str:
    return f"{CONTAINER_MOUNT_ROOT}/m{index}"


def _translate_code_paths(
    code: str,
    mount_paths: list[Path] | None,
    cmd: list[str],
) -> str:
    """Mount host paths and rewrite code to use container-visible Linux paths."""
    if not mount_paths:
        return code

    replacements: list[tuple[str, str]] = []
    for index, original_path in enumerate(mount_paths):
        p = original_path.absolute()
        mount_target = _mount_target_for_index(index)

        if p.is_file():
            source = p.parent
            translated_path = _container_child_path(mount_target, p.name)
        else:
            source = p
            translated_path = mount_target

        _add_bind_mount(cmd, source, mount_target)
        replacements.append((str(p), translated_path))

    # Replace longer paths first in case a parent and child path both appear.
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    translated_code = code
    for host_path, container_path in replacements:
        translated_code = translated_code.replace(host_path, container_path)

    return translated_code

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
    ]
    _add_bind_mount(cmd, state_dir, "/workspace")
    _add_bind_mount(cmd, context_parent, CONTAINER_INPUT_ROOT)
    container_context_path = _container_child_path(CONTAINER_INPUT_ROOT, context_path.name)
    cmd.extend([
        "-w", "/workspace",
        IMAGE_NAME,
        "init", container_context_path
    ])
    
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

    _add_bind_mount(cmd, state_dir, "/workspace")
    _add_bind_mount(cmd, env_file, "/app/.env")
    translated_code = _translate_code_paths(code, mount_paths, cmd)

    cmd.extend([
        "-w", "/workspace",
        IMAGE_NAME,
        "exec"
    ])
    
    result = subprocess.run(cmd, input=translated_code, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def run_status(state_dir: Path, env_file: Path) -> tuple[str, str, int]:
    """Get current REPL state summary."""
    state_dir = state_dir.absolute()
    
    cmd = [
        "docker", "run", "--rm",
        "--env-file", str(env_file),
    ]
    _add_bind_mount(cmd, state_dir, "/workspace")
    cmd.extend([
        "-w", "/workspace",
        IMAGE_NAME,
        "status"
    ])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode
