import warnings

warnings.filterwarnings("ignore", category=Warning)

import os
import sys
import json

import click
from pathlib import Path
from typing import Optional, Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    from ..git.walker import GitWalker
    from ..ast.parser import ASTParser
    from ..ast.lineage import LineageTracker
    from ..github.fetcher import PRFetcher
    from ..github.geographic import GeographicFilter
except ImportError:
    from src.git.walker import GitWalker
    from src.ast.parser import ASTParser
    from src.ast.lineage import LineageTracker
    from src.github.fetcher import PRFetcher
    from src.github.geographic import GeographicFilter


CONFIG_VERSION = "0.1.0"


class Config:
    """Load and manage configuration from file and environment."""

    def __init__(self):
        self.data: dict = {}
        self._load()

    def _load(self):
        """Load config from file and environment."""
        # Try to load .env file if it exists
        env_paths = [
            Path.cwd() / ".env",
            Path.home() / ".env",
        ]

        for env_path in env_paths:
            if env_path.exists() and env_path.is_file():
                try:
                    from dotenv import load_dotenv

                    load_dotenv(env_path)
                    click.echo(f"Loaded .env from {env_path}", err=True)
                except ImportError:
                    # Fallback: manually parse .env
                    for line in env_path.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if "=" in line:
                                key, value = line.split("=", 1)
                                key = key.strip()
                                value = value.strip().strip('"').strip("'")
                                if key and value and not os.environ.get(key):
                                    os.environ[key] = value

        # Load YAML config
        config_paths = [
            Path.cwd() / ".arc.yaml",
            Path.cwd() / ".arc.yml",
            Path.home() / ".arc.yaml",
            Path.home() / ".arc.yml",
            Path(os.environ.get("ARC_CONFIG", "")),
        ]

        for path in config_paths:
            if path.exists() and path.is_file():
                try:
                    import yaml

                    self.data = yaml.safe_load(path.read_text()) or {}
                    click.echo(f"Loaded config from {path}", err=True)
                    break
                except ImportError:
                    pass

        self.data.setdefault(
            "max_commits", int(os.environ.get("ARC_MAX_COMMITS", "100"))
        )
        self.data.setdefault("format", os.environ.get("ARC_FORMAT", "text"))
        self.data.setdefault(
            "verbose", os.environ.get("ARC_VERBOSE", "").lower() in ("1", "true", "yes")
        )
        self.data.setdefault("github_token", os.environ.get("GITHUB_TOKEN", ""))
        self.data.setdefault(
            "claude_api_key",
            os.environ.get("CLAUDE_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


config = Config()


def _find_git_repo(file_path: str) -> str:
    """Find the git repo root by walking up from file_path."""
    current = Path(file_path)
    while current != current.parent:
        if (current / ".git").exists():
            return str(current)
        current = current.parent
    raise ValueError(f"No git repo found for {file_path}")


def _format_output(data: dict, fmt: str) -> str:
    """Format output data based on requested format."""
    if fmt == "json":
        return json.dumps(data, indent=2)
    elif fmt == "table":
        lines = []
        for key, value in data.items():
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value[:5]:
                    if isinstance(item, dict):
                        lines.append(f"  - {item.get('name', item)}")
                    else:
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


def _show_progress(current: int, total: int, message: str = ""):
    """Show progress bar for operations."""
    if not sys.stderr.isatty():
        return
    width = 30
    percent = current / total if total > 0 else 0
    filled = int(width * percent)
    bar = "=" * filled + "-" * (width - filled)
    sys.stderr.write(f"\r[{bar}] {percent:.0%} {message} ({current}/{total})")
    sys.stderr.flush()
    if current >= total:
        sys.stderr.write("\n")


@click.group()
@click.pass_context
@click.version_option(version=CONFIG_VERSION, prog_name="arc")
def cli(ctx):
    """Arc - Code archaeologist. Reconstruct function decision history."""
    import sys

    if (
        "--version" in sys.argv
        or "-v" in sys.argv
        or "--help" in sys.argv
        or "-h" in sys.argv
    ):
        return

    ctx.ensure_object(dict)
    ctx.obj["GITHUB_TOKEN"] = config.get("github_token") or os.environ.get(
        "GITHUB_TOKEN"
    )
    ctx.obj["CLAUDE_API_KEY"] = (
        config.get("claude_api_key")
        or os.environ.get("CLAUDE_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    ctx.obj["GEMINI_API_KEY"] = config.get("gemini_api_key") or os.environ.get(
        "GEMINI_API_KEY"
    )
    ctx.obj["OPENAI_API_KEY"] = config.get("openai_api_key") or os.environ.get(
        "OPENAI_API_KEY"
    )
    ctx.obj["GROQ_API_KEY"] = config.get("groq_api_key") or os.environ.get(
        "GROQ_API_KEY"
    )
    ctx.obj["MODEL"] = config.get("model") or os.environ.get(
        "ARC_MODEL", "gemini/gemini-2.0-flash"
    )
    ctx.obj["VERBOSE"] = config.get("verbose") or os.environ.get(
        "ARC_VERBOSE", ""
    ).lower() in ("1", "true", "yes")


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--repo", "-r", default="", help="GitHub repo (owner/repo)")
@click.option(
    "--max-commits", "-n", default=None, type=int, help="Max commits to analyze"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "table"]),
    default=None,
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Output to file")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.pass_context
def analyze(
    ctx,
    file_path: str,
    repo: str,
    max_commits: Optional[int],
    output_format: Optional[str],
    output: Optional[str],
    verbose: bool,
):
    """Analyze a file and reconstruct its decision history."""
    max_commits = max_commits or config.get("max_commits", 100)
    output_format = output_format or config.get("format", "text")

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

    changes = []
    for edge in edges[:10]:
        parent_hash = git.get_commit_parent(edge.commit_hash)
        full_diff = git.get_full_diff(edge.commit_hash, str(relative_path), parent_hash)

        func_name = relative_path.stem
        node_content = git.get_file_at_commit(edge.commit_hash, str(relative_path))
        function_diff = full_diff
        if node_content:
            tree = ast.parse_file(node_content, language)
            if tree:
                node = ast.find_node_by_name(tree, language, func_name)
                if node:
                    function_diff = git.filter_diff_to_function(
                        full_diff, node.start_line, node.end_line
                    )

        change = {
            "commit_hash": edge.commit_hash,
            "commit_message": edge.commit_message,
            "author": edge.author,
            "date": edge.date,
            "diff": function_diff,
        }
        changes.append(change)

    result = {
        "file": str(relative_path),
        "function": relative_path.stem,
        "repo": repo_path,
        "language": language,
        "lineage_edges": len(edges),
        "changes": changes,
    }

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("function_name")
@click.option("--repo", "-r", default="", help="GitHub repo (owner/repo)")
@click.option(
    "--max-commits", "-n", default=None, type=int, help="Max commits to analyze"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "table"]),
    default=None,
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
    max_commits: Optional[int],
    output_format: Optional[str],
    output: Optional[str],
    verbose: bool,
):
    """Analyze a specific function and reconstruct its decision history."""
    max_commits = max_commits or config.get("max_commits", 100)
    output_format = output_format or config.get("format", "text")

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

    changes = []
    for edge in edges[:10]:
        parent_hash = git.get_commit_parent(edge.commit_hash)
        full_diff = git.get_full_diff(edge.commit_hash, str(relative_path), parent_hash)

        node_content = git.get_file_at_commit(edge.commit_hash, str(relative_path))
        function_diff = full_diff
        if node_content and full_diff:
            tree = ast.parse_file(node_content, language)
            if tree:
                node = ast.find_node_by_name(tree, language, function_name)
                if node:
                    filtered = git.filter_diff_to_function(
                        full_diff, node.start_line, node.end_line
                    )
                    if filtered:
                        function_diff = filtered

        change = {
            "commit_hash": edge.commit_hash,
            "commit_message": edge.commit_message,
            "author": edge.author,
            "date": edge.date,
            "diff": function_diff,
        }
        changes.append(change)

    result = {
        "file": str(relative_path),
        "function": function_name,
        "repo": repo_path,
        "language": language,
        "lineage_edges": len(edges),
        "changes": changes,
    }

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "table"]),
    default=None,
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Output to file")
def list_functions(file_path: str, output_format: Optional[str], output: Optional[str]):
    """List all functions in a file."""
    output_format = output_format or config.get("format", "text")
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

    output_str = _format_output(result, output_format)

    if output:
        Path(output).write_text(output_str)
        click.echo(f"Output saved to {output}")
    else:
        click.echo(output_str)


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.argument("function_name")
@click.option("--max-files", "-n", default=20, type=int, help="Max files to search")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "table"]),
    default=None,
    help="Output format",
)
@click.option("--output", "-o", type=click.Path(), help="Output to file")
def search(
    repo_path: str,
    function_name: str,
    max_files: int,
    output_format: Optional[str],
    output: Optional[str],
):
    """Search for a function across all files in a repository."""
    output_format = output_format or config.get("format", "text")

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

    file_count = 0
    for path in Path(repo_path).rglob("*"):
        if path.suffix not in extensions or len(results) >= max_files:
            continue
        file_count += 1
        _show_progress(file_count, max_files * 2, "Scanning files")
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

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True), default=".")
def stats(repo_path: str):
    """Show repository statistics."""
    repo_path = str(Path(repo_path).resolve())
    git = GitWalker(repo_path)
    ast = ASTParser()

    extensions = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".cpp",
        ".rb",
        ".php",
    }
    file_counts = {}
    function_counts = {}

    click.echo(f"Analyzing repository: {repo_path}")

    for path in Path(repo_path).rglob("*"):
        if path.suffix not in extensions or ".git" in str(path):
            continue
        try:
            lang = ast.detect_language(str(path)) or "unknown"
            file_counts[lang] = file_counts.get(lang, 0) + 1

            content = path.read_text()
            tree = ast.parse_file(content, lang)
            if tree:
                nodes = ast.extract_nodes(tree, lang)
                for node in nodes:
                    if node.node_type in (
                        "function_definition",
                        "function_declaration",
                        "function_item",
                        "method",
                        "def",
                    ):
                        function_counts[lang] = function_counts.get(lang, 0) + 1
        except Exception:
            continue

    commits = git.get_commits_for_file(".", max_count=1000)

    result = {
        "repo": repo_path,
        "files_by_language": file_counts,
        "functions_by_language": function_counts,
        "total_files": sum(file_counts.values()),
        "total_functions": sum(function_counts.values()),
        "commit_count": len(commits),
    }

    click.echo(f"\nRepository Statistics:")
    click.echo(f"  Total files: {result['total_files']}")
    click.echo(f"  Total functions: {result['total_functions']}")
    click.echo(f"  Total commits: {result['commit_count']}")
    click.echo(f"\nFiles by language:")
    for lang, count in sorted(file_counts.items(), key=lambda x: -x[1]):
        click.echo(f"  {lang}: {count}")


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("function_name", required=False)
@click.option("--max-commits", "-n", default=50, type=int, help="Max commits to show")
def history(
    file_path: str,
    function_name: Optional[str],
    max_commits: int,
):
    """Show commit history for a file or function with diffs."""
    resolved_path = str(Path(file_path).resolve())
    repo_path = _find_git_repo(resolved_path)
    relative_path = Path(resolved_path).relative_to(repo_path)

    git = GitWalker(repo_path)
    commits = git.get_commits_for_file(str(relative_path), max_count=max_commits)

    history = []
    for commit in commits:
        parent_hash = git.get_commit_parent(commit.hash)
        full_diff = git.get_full_diff(commit.hash, str(relative_path), parent_hash)

        history.append(
            {
                "commit_hash": commit.hash,
                "commit_message": commit.message,
                "author": commit.author,
                "date": commit.date,
                "diff": full_diff,
            }
        )

    result = {
        "file": str(relative_path),
        "function": function_name,
        "repo": repo_path,
        "history": history,
    }

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@cli.command()
@click.argument("commit_hash")
@click.argument("file_path", type=click.Path(exists=True))
def diff(commit_hash: str, file_path: str):
    """Show diff for a specific commit and file."""
    resolved_path = str(Path(file_path).resolve())
    repo_path = _find_git_repo(resolved_path)
    relative_path = str(Path(resolved_path).relative_to(repo_path))

    git = GitWalker(repo_path)

    parent = git.get_commit_parent(commit_hash)
    if not parent:
        click.echo("Error: Cannot get parent commit", err=True)
        return

    diffs = git.get_diff_for_commit(commit_hash, relative_path, parent)

    if not diffs:
        click.echo("No diff found for this commit.")
        return

    click.echo(f"Diff for {relative_path} at {commit_hash[:8]}:\n")

    for diff in diffs:
        click.echo(
            f"@@ -{diff.old_start},{diff.old_lines} +{diff.new_start},{diff.new_lines} @@"
        )
        click.echo(f"  Added: {len(diff.added_lines)} lines")
        click.echo(f"  Deleted: {len(diff.deleted_lines)} lines")


@cli.command()
@click.argument("path", type=click.Path(), default=".")
def init(path: str):
    """Initialize config file in current directory."""
    config_path = Path(path) / ".arc.yaml"

    if config_path.exists():
        click.echo(f"Config file already exists: {config_path}", err=True)
        return

    template = """# Arc - Code Archaeologist Configuration
# https://github.com/yourusername/archeologist

# GitHub personal access token (for PR integration)
# github_token: ghp_xxx

# Claude API key (for narrative synthesis)
# claude_api_key: sk-ant-xxx

# Default max commits to analyze
max_commits: 100

# Default output format (text, json, table)
format: text

# Enable verbose output
verbose: false
"""

    config_path.write_text(template)
    click.echo(f"Created config file: {config_path}")
    click.echo("\nEdit the config file to add your API keys.")


@cli.command()
def validate():
    """Validate config file."""
    config_paths = [
        Path.cwd() / ".arc.yaml",
        Path.cwd() / ".arc.yml",
        Path.home() / ".arc.yaml",
        Path.home() / ".arc.yml",
    ]

    found = False
    for path in config_paths:
        if path.exists() and path.is_file():
            found = True
            try:
                import yaml

                data = yaml.safe_load(path.read_text())
                click.echo(f"✓ Config valid: {path}")
                click.echo(f"  Keys: {list(data.keys()) if data else 'none'}")
            except ImportError:
                click.echo(
                    f"✓ Config file exists: {path} (yaml not installed, can't validate)"
                )
            except Exception as e:
                click.echo(f"✗ Config error: {path}: {e}", err=True)

    if not found:
        click.echo("No config file found. Run 'arc init' to create one.")

    click.echo(f"\nEnvironment variables:")
    click.echo(f"  ARC_MAX_COMMITS: {os.environ.get('ARC_MAX_COMMITS', 'not set')}")
    click.echo(f"  ARC_FORMAT: {os.environ.get('ARC_FORMAT', 'not set')}")
    click.echo(f"  ARC_VERBOSE: {os.environ.get('ARC_VERBOSE', 'not set')}")
    click.echo(f"  ARC_MODEL: {os.environ.get('ARC_MODEL', 'not set')}")
    click.echo(
        f"  GITHUB_TOKEN: {'set' if os.environ.get('GITHUB_TOKEN') else 'not set'}"
    )
    click.echo(
        f"  GEMINI_API_KEY: {'set' if os.environ.get('GEMINI_API_KEY') else 'not set'}"
    )
    click.echo(
        f"  OPENAI_API_KEY: {'set' if os.environ.get('OPENAI_API_KEY') else 'not set'}"
    )
    click.echo(
        f"  GROQ_API_KEY: {'set' if os.environ.get('GROQ_API_KEY') else 'not set'}"
    )
    click.echo(
        f"  CLAUDE_API_KEY: {'set' if os.environ.get('CLAUDE_API_KEY') else 'not set'}"
    )


if __name__ == "__main__":
    cli()
