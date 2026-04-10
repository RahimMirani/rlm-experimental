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
    }
}


def validate_config(config: Dict[str, Any]) -> None:
    """Validate configuration structure and values.

    Raises:
        ValueError: If configuration is invalid
    """
    required_sections = ["root_llm", "sub_llm", "memory_compaction"]
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
