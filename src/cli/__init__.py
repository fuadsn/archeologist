import os
import click
from pathlib import Path

try:
    from ..git.walker import GitWalker
    from ..ast.parser import ASTParser
    from ..ast.lineage import LineageTracker
    from ..github.fetcher import PRFetcher
    from ..github.geographic import GeographicFilter
    from ..synthesis.narrative import NarrativeSynthesizer
except ImportError:
    from src.git.walker import GitWalker
    from src.ast.parser import ASTParser
    from src.ast.lineage import LineageTracker
    from src.github.fetcher import PRFetcher
    from src.github.geographic import GeographicFilter
    from src.synthesis.narrative import NarrativeSynthesizer


@click.group()
@click.pass_context
def cli(ctx):
    """Arc - Code archaeologist. Reconstruct function decision history."""
    ctx.ensure_object(dict)
    ctx.obj["GITHUB_TOKEN"] = os.environ.get("GITHUB_TOKEN")
    ctx.obj["CLAUDE_API_KEY"] = os.environ.get("CLAUDE_API_KEY") or os.environ.get(
        "ANTHROPIC_API_KEY"
    )


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--repo", "-r", default="", help="GitHub repo (owner/repo)")
@click.option("--max-commits", "-n", default=100, help="Max commits to analyze")
@click.pass_context
def analyze(ctx, file_path: str, repo: str, max_commits: int):
    """Analyze a file and reconstruct its decision history."""
    if not repo:
        click.echo("Error: --repo required (e.g., fastapi/fastapi)", err=True)
        return

    click.echo(f"Analyzing {file_path}...")

    file_path = str(Path(file_path).resolve())
    repo_path = os.environ.get("GIT_REPO_PATH", os.getcwd())

    git = GitWalker(repo_path)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    language = ast.detect_language(file_path) or "python"
    file_name = Path(file_path).name

    edges = tracker.track_lineage(
        file_name, file_name.split(".")[0], language, max_commits
    )

    click.echo(f"Found {len(edges)} lineage edges")

    pr_fetcher = None
    if ctx.obj.get("GITHUB_TOKEN"):
        pr_fetcher = PRFetcher(ctx.obj["GITHUB_TOKEN"])

    synthesizer = NarrativeSynthesizer()

    lineage_data = []
    for edge in edges[:10]:
        lineage_data.append(
            {
                "change_type": edge.change_type,
                "confidence": edge.confidence,
                "parent": edge.parent_node_id,
                "child": edge.child_node_id,
            }
        )

    summary = synthesizer.synthesize_simple(lineage_data, [])
    click.echo(f"Summary: {summary}")

    click.echo(
        "\nTo get full narrative, set CLAUDE_API_KEY and run with LLM synthesis."
    )


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("function_name")
@click.option("--repo", "-r", default="", help="GitHub repo (owner/repo)")
@click.option("--max-commits", "-n", default=100, help="Max commits to analyze")
@click.pass_context
def analyze_function(
    ctx, file_path: str, function_name: str, repo: str, max_commits: int
):
    """Analyze a specific function and reconstruct its decision history."""
    if not repo:
        click.echo("Error: --repo required (e.g., fastapi/fastapi)", err=True)
        return

    click.echo(f"Analyzing function {function_name} in {file_path}...")

    file_path = str(Path(file_path).resolve())
    repo_path = os.environ.get("GIT_REPO_PATH", os.getcwd())

    git = GitWalker(repo_path)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    language = ast.detect_language(file_path) or "python"
    file_name = Path(file_path).name

    edges = tracker.track_lineage(file_name, function_name, language, max_commits)

    click.echo(f"Found {len(edges)} lineage edges for {function_name}")

    if not edges:
        click.echo("No lineage found. Function may not have changed.")
        return

    pr_fetcher = None
    if ctx.obj.get("GITHUB_TOKEN") and repo:
        pr_fetcher = PRFetcher(ctx.obj["GITHUB_TOKEN"])
        geo_filter = GeographicFilter(ast)

    synthesizer = NarrativeSynthesizer()

    lineage_data = []
    for edge in edges[:10]:
        lineage_data.append(
            {"change_type": edge.change_type, "confidence": edge.confidence}
        )

    if ctx.obj.get("CLAUDE_API_KEY"):
        click.echo("Generating narrative with LLM...")
        result = synthesizer.synthesize(lineage_data, [], "", function_name)
        click.echo(f"\n{result}")
    else:
        summary = synthesizer.synthesize_simple(lineage_data, [])
        click.echo(f"Summary: {summary}")
        click.echo("\nSet CLAUDE_API_KEY for full narrative synthesis.")


if __name__ == "__main__":
    cli()
