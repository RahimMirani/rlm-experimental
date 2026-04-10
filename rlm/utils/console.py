from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
import time

console = Console()

def print_tool_call(code: str):
    """Print the Python code being sent to the REPL."""
    syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
    panel = Panel(
        syntax,
        title="[bold blue]Root LLM → REPL (Python Code)[/bold blue]",
        border_style="blue",
        expand=False
    )
    console.print(panel)

def print_tool_result(result: str):
    """Print the result received from the REPL."""
    panel = Panel(
        Text(result),
        title="[bold green]REPL Result[/bold green]",
        border_style="green",
        expand=False
    )
    console.print(panel)

def print_assistant_answer(answer: str):
    """Print the final answer from the Assistant."""
    panel = Panel(
        answer,
        title="[bold magenta]Assistant Answer[/bold magenta]",
        border_style="magenta",
        expand=False
    )
    console.print(panel)

def print_final_answer(answer: str):
    """Print the final answer delivered directly from the REPL."""
    panel = Panel(
        answer,
        title="[bold cyan]Final Answer (from REPL)[/bold cyan]",
        border_style="cyan",
        expand=False
    )
    console.print(panel)

def get_status_spinner(message: str = "Thinking..."):
    """Return a live status context manager."""
    return console.status(f"[bold yellow]{message}[/bold yellow]", spinner="dots")
