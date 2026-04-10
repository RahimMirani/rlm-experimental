import os
import sys
import click
from pathlib import Path
from dotenv import load_dotenv
from rlm.orchestrator.tools import docker_runner
from rlm.orchestrator import orchestrator
from rlm.config import load_config, apply_cli_overrides
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE = Path(".rlm_state")
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_DOCKERFILE = Path("docker/Dockerfile")
ROOT_DIR = Path(".")

@click.group()
@click.option('--workspace', type=click.Path(), default=str(DEFAULT_WORKSPACE), help='Workspace directory for state.')
@click.option('--env-file', type=click.Path(), default=str(DEFAULT_ENV_FILE), help='Path to .env file with API keys.')
@click.pass_context
def cli(ctx, workspace, env_file):
    """RLM (Reasoning Language Model) CLI."""
    ctx.ensure_object(dict)
    ctx.obj['workspace'] = Path(workspace)
    ctx.obj['env_file'] = Path(env_file)

    ctx.obj['workspace'].mkdir(parents=True, exist_ok=True)

    docker_runner.build_image(DEFAULT_DOCKERFILE, ROOT_DIR)

@cli.command()
@click.argument('context_file', type=click.Path(exists=True))
@click.pass_context
def init(ctx, context_file):
    """Initialize a session with a context file."""
    workspace = ctx.obj['workspace']
    env_file = ctx.obj['env_file']

    stdout, stderr, exit_code = docker_runner.run_init(Path(context_file), workspace, env_file)

    if exit_code == 0:
        click.echo(stdout)
    else:
        click.echo(f"Error during initialization:\n{stderr}", err=True)
        sys.exit(exit_code)

@cli.command()
@click.option('--model', help='Override root LLM model (e.g., openai/gpt-4o, anthropic/claude-3-opus)')
@click.option('--subllm', help='Override sub-LLM model (e.g., openai/gpt-4o-mini)')
@click.option('--compact/--no-compact', default=None, help='Enable or disable memory compaction (summarization).')
@click.pass_context
def chat(ctx, model, subllm, compact):
    """Start an interactive chat session."""
    workspace = ctx.obj['workspace']
    env_file = ctx.obj['env_file']

    if not env_file.exists():
        click.echo(f"Warning: .env file not found at {env_file}. API calls may fail.", err=True)
    load_dotenv(env_file)

    try:
        config = load_config()
        logger.info(f"Loaded configuration from config.json")
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    try:
        config = apply_cli_overrides(config, model=model, subllm=subllm, compact=compact)
    except ValueError as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    orch = orchestrator.Orchestrator(config, env_file, workspace)

    click.echo("RLM Chat Session Started. Type 'exit' or 'quit' to end.")
    while True:
        query = click.prompt("User")
        if query.lower() in ('exit', 'quit'):
            break

        try:
            orch.run(query)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)

@cli.command()
@click.argument('query')
@click.option('--model', help='Override root LLM model (e.g., openai/gpt-4o, anthropic/claude-3-opus)')
@click.option('--subllm', help='Override sub-LLM model (e.g., openai/gpt-4o-mini)')
@click.option('--compact/--no-compact', default=None, help='Enable or disable memory compaction (summarization).')
@click.pass_context
def run(ctx, query, model, subllm, compact):
    """Run a single query and exit."""
    workspace = ctx.obj['workspace']
    env_file = ctx.obj['env_file']

    if not env_file.exists():
        click.echo(f"Warning: .env file not found at {env_file}. API calls may fail.", err=True)
    load_dotenv(env_file)

    try:
        config = load_config()
        logger.info(f"Loaded configuration from config.json")
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    try:
        config = apply_cli_overrides(config, model=model, subllm=subllm, compact=compact)
    except ValueError as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    orch = orchestrator.Orchestrator(config, env_file, workspace)

    try:
        orch.run(query)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@cli.command()
@click.pass_context
def status(ctx):
    """Show current REPL state."""
    workspace = ctx.obj['workspace']
    env_file = ctx.obj['env_file']

    stdout, stderr, exit_code = docker_runner.run_status(workspace, env_file)
    if exit_code == 0:
        click.echo(stdout)
    else:
        click.echo(f"Error getting status:\n{stderr}", err=True)
        sys.exit(exit_code)

def main():
    cli(obj={})

if __name__ == '__main__':
    main()
