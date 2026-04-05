import click
import os
from pathlib import Path


@click.group()
@click.pass_context
def cli(ctx):
    """Code archaeologist - reconstruct function decision history."""
    ctx.ensure_object(dict)
    ctx.obj["GITHUB_TOKEN"] = os.environ.get("GITHUB_TOKEN")
    ctx.obj["CLAUDE_API_KEY"] = os.environ.get("CLAUDE_API_KEY")


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.pass_context
def analyze(ctx, file_path):
    """Analyze a file and reconstruct its decision history."""
    click.echo(f"Analyzing {file_path}...")


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("function_name")
@click.pass_context
def analyze_function(ctx, file_path, function_name):
    """Analyze a specific function and reconstruct its decision history."""
    click.echo(f"Analyzing function {function_name} in {file_path}...")


if __name__ == "__main__":
    cli()
