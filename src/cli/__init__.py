import os
import click
from pathlib import Path
from typing import Optional

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


def _format_output(data: dict, format: str) -> str:
    """Format output data based on requested format."""
    if format == "json":
        import json

        return json.dumps(data, indent=2)
    elif format == "table":
        lines = []
        for key, value in data.items():
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value[:5]:
                    lines.append(f"  - {item}")
                if len(value) > 5:
                    lines.append(f"  ... and {len(value) - 5} more")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)
    else:
        parts = []
        for key, value in data.items():
            if isinstance(value, list):
                parts.append(f"{key}: {len(value)} items")
            else:
                parts.append(f"{key}: {value}")
        return " | ".join(parts)


@click.group()
@click.pass_context
def cli(ctx):
    """Arc - Code archaeologist. Reconstruct function decision history."""
    ctx.ensure_object(dict)
    ctx.obj["GITHUB_TOKEN"] = os.environ.get("GITHUB_TOKEN")
    ctx.obj["CLAUDE_API_KEY"] = os.environ.get("CLAUDE_API_KEY") or os.environ.get(
        "ANTHROPIC_API_KEY"
    )
    ctx.obj["VERBOSE"] = os.environ.get("ARC_VERBOSE", "").lower() in (
        "1",
        "true",
        "yes",
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
@click.option(
    "--format",
    "-f",
    type=click.Choice(["text", "json", "table"]),
    default="text",
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Output to file")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.pass_context
def analyze(
    ctx,
    file_path: str,
    repo: str,
    max_commits: int,
    format: str,
    output: Optional[str],
    verbose: bool,
):
    """Analyze a file and reconstruct its decision history."""
    resolved_path = str(Path(file_path).resolve())
    if verbose or ctx.obj.get("VERBOSE"):
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

    if verbose or ctx.obj.get("VERBOSE"):
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
            if pr and (verbose or ctx.obj.get("VERBOSE")):
                click.echo(f"  PR #{pr.number}: {pr.title}")

    summary = synthesizer.synthesize_simple(lineage_data, [])

    result = {
        "file": resolved_path,
        "repo": repo_path,
        "language": language,
        "lineage_edges": len(edges),
        "summary": summary,
        "changes": lineage_data[:10],
    }

    output_str = _format_output(result, format)

    if output:
        Path(output).write_text(output_str)
        click.echo(f"Output saved to {output}")
    else:
        click.echo(output_str)

    if format == "text":
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
@click.option(
    "--format",
    "-f",
    type=click.Choice(["text", "json", "table"]),
    default="text",
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Output to file")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.pass_context
def analyze_function(
    ctx,
    file_path: str,
    function_name: str,
    repo: str,
    max_commits: int,
    format: str,
    output: Optional[str],
    verbose: bool,
):
    """Analyze a specific function and reconstruct its decision history."""
    resolved_path = str(Path(file_path).resolve())

    if verbose or ctx.obj.get("VERBOSE"):
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

    if verbose or ctx.obj.get("VERBOSE"):
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
                if verbose or ctx.obj.get("VERBOSE"):
                    click.echo(f"  PR #{pr.number}: {pr.title}")

    if ctx.obj.get("CLAUDE_API_KEY"):
        click.echo("\nGenerating narrative with LLM...")
        result_narrative = synthesizer.synthesize(lineage_data, [], "", function_name)
        narrative = result_narrative
    else:
        summary = synthesizer.synthesize_simple(lineage_data, [])
        narrative = summary

    result = {
        "function": function_name,
        "file": resolved_path,
        "repo": repo_path,
        "language": language,
        "lineage_edges": len(edges),
        "narrative": narrative,
        "changes": [
            {
                "type": e.change_type,
                "confidence": round(e.confidence, 2),
                "commit": e.commit_hash[:8] if e.commit_hash else "",
                "message": (e.commit_message or "").split("\n")[0],
            }
            for e in edges[:10]
        ],
    }

    output_str = _format_output(result, format)

    if output:
        Path(output).write_text(output_str)
        click.echo(f"Output saved to {output}")
    else:
        click.echo(output_str)

    if format == "text" and not ctx.obj.get("CLAUDE_API_KEY"):
        click.echo("\nSet CLAUDE_API_KEY for full narrative synthesis.")


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "-f",
    type=click.Choice(["text", "json", "table"]),
    default="text",
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Output to file")
def list_functions(file_path: str, format: str, output: Optional[str]):
    """List all functions in a file."""
    resolved_path = str(Path(file_path).resolve())

    ast = ASTParser()
    language = ast.detect_language(resolved_path) or "python"

    with open(resolved_path, "r") as f:
        content = f.read()

    tree = ast.parse_file(content, language)
    if not tree:
        click.echo("Error: Failed to parse file", err=True)
        return

    nodes = ast.extract_nodes(tree, language)

    functions = []
    classes = []
    for n in nodes:
        if n.node_type in (
            "function_definition",
            "function_declaration",
            "function_item",
            "method",
            "def",
        ):
            functions.append(
                {"name": n.name, "line": n.start_line, "end_line": n.end_line}
            )
        elif n.node_type in ("class_definition", "class_declaration", "class"):
            classes.append(
                {"name": n.name, "line": n.start_line, "end_line": n.end_line}
            )

    result = {
        "file": resolved_path,
        "language": language,
        "functions": functions,
        "classes": classes,
        "total_functions": len(functions),
        "total_classes": len(classes),
    }

    output_str = _format_output(result, format)

    if output:
        Path(output).write_text(output_str)
        click.echo(f"Output saved to {output}")
    else:
        click.echo(output_str)


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.argument("function_name")
@click.option("--max-files", "-n", default=20, help="Max files to search")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["text", "json", "table"]),
    default="text",
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Output to file")
def search(
    repo_path: str,
    function_name: str,
    max_files: int,
    format: str,
    output: Optional[str],
):
    """Search for a function across all files in a repository."""
    git = GitWalker(repo_path)
    ast = ASTParser()

    results = []
    extensions = {
        ".py",
        ".js",
        ".ts",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".cpp",
        ".rb",
        ".php",
    }

    click.echo(f"Searching for '{function_name}' in {repo_path}...")

    for path in Path(repo_path).rglob("*"):
        if path.suffix not in extensions or len(results) >= max_files:
            continue
        try:
            content = path.read_text()
            tree = ast.parse_file(content, ast.detect_language(str(path)) or "python")
            if tree:
                nodes = ast.extract_nodes(
                    tree, ast.detect_language(str(path)) or "python"
                )
                for node in nodes:
                    if node.name == function_name:
                        results.append(
                            {
                                "file": str(path.relative_to(repo_path)),
                                "line": node.start_line,
                                "type": node.node_type,
                            }
                        )
        except Exception:
            continue

    result = {
        "function": function_name,
        "repo": repo_path,
        "matches": results,
        "count": len(results),
    }

    output_str = _format_output(result, format)

    if output:
        Path(output).write_text(output_str)
        click.echo(f"Output saved to {output}")
    else:
        click.echo(output_str)


if __name__ == "__main__":
    cli()
