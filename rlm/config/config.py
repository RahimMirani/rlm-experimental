"""Configuration management for RLM.

Loads and validates configuration from config.json in the root directory.
All model and provider settings come from config.json, while API keys
are loaded from .env file.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.json")
DEFAULT_FALLBACK_CONFIG = {
    "root_llm": {
        "model": "openai/gpt-4o"
    },
    "sub_llm": {
        "model": "openai/gpt-4o-mini"
    },
    "memory_compaction": {
        "enabled": True
    },
    "tracing": {
        "enabled": True,
        "log_dir": "logs/traces",
        "capture_repl_code": True,
        "capture_state_snapshots": True,
        "capture_sub_llm": True
    },
    "max_iterations": 25
}


def _merge_config_defaults(config: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged = config.copy()
    for key, default_value in defaults.items():
        if key not in merged:
            merged[key] = default_value.copy() if isinstance(default_value, dict) else default_value
            continue
        if isinstance(default_value, dict) and isinstance(merged[key], dict):
            merged[key] = _merge_config_defaults(merged[key], default_value)
    return merged


def validate_config(config: Dict[str, Any]) -> None:
    """Validate configuration structure and values.

    Raises:
        ValueError: If configuration is invalid
    """
    required_sections = ["root_llm", "sub_llm", "memory_compaction", "tracing"]
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required configuration section: {section}")

    for key in ("root_llm", "sub_llm"):
        if "model" not in config[key]:
            raise ValueError(f"Missing 'model' in {key} configuration")
        model = config[key]["model"]
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"{key}.model must be a non-empty string")
        if "/" not in model:
            raise ValueError(
                f"{key}.model must use LiteLLM format (provider/model), got: {model}"
            )

    compact_config = config["memory_compaction"]
    if "enabled" not in compact_config:
        raise ValueError("Missing 'enabled' in memory_compaction configuration")
    if not isinstance(compact_config["enabled"], bool):
        raise ValueError("memory_compaction.enabled must be a boolean")

    tracing_config = config["tracing"]
    tracing_bool_keys = [
        "enabled",
        "capture_repl_code",
        "capture_state_snapshots",
        "capture_sub_llm",
    ]
    for key in tracing_bool_keys:
        if key not in tracing_config:
            raise ValueError(f"Missing '{key}' in tracing configuration")
        if not isinstance(tracing_config[key], bool):
            raise ValueError(f"tracing.{key} must be a boolean")

    log_dir = tracing_config.get("log_dir")
    if not isinstance(log_dir, str) or not log_dir.strip():
        raise ValueError("tracing.log_dir must be a non-empty string")

    max_iterations = config.get("max_iterations")
    if not isinstance(max_iterations, int) or max_iterations <= 0:
        raise ValueError("max_iterations must be a positive integer")

    logger.info("Configuration validation passed")


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Load configuration from config.json.

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config.json doesn't exist
        ValueError: If configuration is invalid
    """
    if not config_path.exists():
        logger.warning(
            f"Configuration file not found at {config_path}. "
            f"Using default configuration. Please create config.json."
        )
        return DEFAULT_FALLBACK_CONFIG.copy()

    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {config_path}: {e}")

    config = _merge_config_defaults(config, DEFAULT_FALLBACK_CONFIG)
    validate_config(config)

    logger.info(f"Loaded configuration from {config_path}")
    return config


def apply_cli_overrides(
    config: Dict[str, Any],
    model: str | None = None,
    subllm: str | None = None,
    compact: bool | None = None
) -> Dict[str, Any]:
    """Apply CLI flag overrides to configuration.

    Returns:
        Configuration dictionary with overrides applied
    """
    config = config.copy()
    config["root_llm"] = config["root_llm"].copy()
    config["sub_llm"] = config["sub_llm"].copy()
    config["memory_compaction"] = config["memory_compaction"].copy()
    config["tracing"] = config["tracing"].copy()

    if model:
        if "/" not in model:
            raise ValueError(
                f"Model must use LiteLLM format (provider/model), got: {model}"
            )
        config["root_llm"]["model"] = model
        logger.info(f"Override: root_llm.model = {model}")

    if subllm:
        if "/" not in subllm:
            raise ValueError(
                f"Model must use LiteLLM format (provider/model), got: {subllm}"
            )
        config["sub_llm"]["model"] = subllm
        logger.info(f"Override: sub_llm.model = {subllm}")

    if compact is not None:
        config["memory_compaction"]["enabled"] = compact
        logger.info(f"Override: memory_compaction.enabled = {compact}")

    return config
