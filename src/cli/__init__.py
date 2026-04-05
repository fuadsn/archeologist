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


def _find_git_repo(file_path: str) -> str:
    """Find the git repo root by walking up from file_path."""
    current = Path(file_path)
    while current != current.parent:
        if (current / ".git").exists():
            return str(current)
        current = current.parent
    raise ValueError(f"No git repo found for {file_path}")


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
@click.option(
    "--repo",
    "-r",
    default="",
    help="GitHub repo (owner/repo) - optional for local analysis",
)
@click.option("--max-commits", "-n", default=100, help="Max commits to analyze")
@click.pass_context
def analyze(ctx, file_path: str, repo: str, max_commits: int):
    """Analyze a file and reconstruct its decision history."""
    resolved_path = str(Path(file_path).resolve())
    click.echo(f"Analyzing {resolved_path}...")

    repo_path = os.environ.get("GIT_REPO_PATH", _find_git_repo(resolved_path))

    git = GitWalker(repo_path)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    language = ast.detect_language(resolved_path) or "python"
    relative_path = Path(resolved_path).relative_to(repo_path)

    edges = tracker.track_lineage(
        str(relative_path), relative_path.stem, language, max_commits
    )

    click.echo(f"Found {len(edges)} lineage edges")

    pr_fetcher = None
    if ctx.obj.get("GITHUB_TOKEN") and repo:
        pr_fetcher = PRFetcher(ctx.obj["GITHUB_TOKEN"])

    synthesizer = NarrativeSynthesizer()

    lineage_data = []
    for edge in edges[:10]:
        lineage_data.append(
            {
                "change_type": edge.change_type,
                "confidence": edge.confidence,
                "commit_hash": edge.commit_hash,
                "commit_message": edge.commit_message,
            }
        )
        if pr_fetcher and repo:
            pr = pr_fetcher.get_pr_from_commit(
                repo, edge.commit_hash, edge.commit_message
            )
            if pr:
                click.echo(f"  PR #{pr.number}: {pr.title}")

    summary = synthesizer.synthesize_simple(lineage_data, [])
    click.echo(f"\nSummary: {summary}")

    click.echo(
        "\nTo get full narrative, set CLAUDE_API_KEY and run with LLM synthesis."
    )


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("function_name")
@click.option(
    "--repo",
    "-r",
    default="",
    help="GitHub repo (owner/repo) - optional for local analysis",
)
@click.option("--max-commits", "-n", default=100, help="Max commits to analyze")
@click.pass_context
def analyze_function(
    ctx, file_path: str, function_name: str, repo: str, max_commits: int
):
    """Analyze a specific function and reconstruct its decision history."""
    resolved_path = str(Path(file_path).resolve())
    click.echo(f"Analyzing function {function_name} in {resolved_path}...")

    repo_path = os.environ.get("GIT_REPO_PATH", _find_git_repo(resolved_path))

    git = GitWalker(repo_path)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    language = ast.detect_language(resolved_path) or "python"
    relative_path = Path(resolved_path).relative_to(repo_path)

    edges = tracker.track_lineage(
        str(relative_path), function_name, language, max_commits
    )

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
    commit_to_pr = {}
    for edge in edges[:10]:
        lineage_data.append(
            {
                "change_type": edge.change_type,
                "confidence": edge.confidence,
                "commit_hash": edge.commit_hash,
                "commit_message": edge.commit_message,
            }
        )
        if pr_fetcher and repo:
            pr = pr_fetcher.get_pr_from_commit(
                repo, edge.commit_hash, edge.commit_message
            )
            if pr:
                commit_to_pr[edge.commit_hash[:8]] = pr
                click.echo(f"  PR #{pr.number}: {pr.title}")

    if ctx.obj.get("CLAUDE_API_KEY"):
        click.echo("\nGenerating narrative with LLM...")
        result = synthesizer.synthesize(lineage_data, [], "", function_name)
        click.echo(f"\n{result}")
    else:
        summary = synthesizer.synthesize_simple(lineage_data, [])
        click.echo(f"\nSummary: {summary}")
        click.echo("\nSet CLAUDE_API_KEY for full narrative synthesis.")


if __name__ == "__main__":
    cli()
