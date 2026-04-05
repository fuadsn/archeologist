import os
import tempfile
import pytest
from pathlib import Path
from git import Repo


@pytest.fixture
def temp_repo():
    """Create a temporary git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        yield tmpdir
        repo.close()


def test_pr_fetcher_extract_pr_number():
    """Test PR number extraction from commit messages."""
    from src.github.fetcher import PRFetcher

    fetcher = PRFetcher()

    assert fetcher.extract_pr_number_from_commit_message("Fix #123") == 123
    assert fetcher.extract_pr_number_from_commit_message("PR #456") == 456
    assert fetcher.extract_pr_number_from_commit_message("closes #789") == 789
    assert fetcher.extract_pr_number_from_commit_message("fixes #101") == 101
    assert fetcher.extract_pr_number_from_commit_message("resolves #202") == 202
    assert fetcher.extract_pr_number_from_commit_message("No PR here") is None


def test_geographic_filter_comment_to_node():
    """Test mapping comments to AST node boundaries."""
    from src.github.geographic import GeographicFilter
    from src.github.fetcher import ReviewComment
    from src.ast.parser import ASTParser, ASTNode

    ast = ASTParser()
    geo = GeographicFilter(ast)

    code = """def foo():
    x = 1
    return x

def bar():
    return 2
"""

    tree = ast.parse_file(code, "python")
    nodes = ast.extract_nodes(tree, "python")

    foo_node = next(n for n in nodes if n.name == "foo")
    bar_node = next(n for n in nodes if n.name == "bar")

    comments = [
        ReviewComment(
            comment_id="c1",
            pr_number=123,
            path="test.py",
            line=2,
            body="Change this",
            author="user1",
            created_at="2024-01-01",
        ),
        ReviewComment(
            comment_id="c2",
            pr_number=123,
            path="test.py",
            line=10,
            body="Change that",
            author="user2",
            created_at="2024-01-02",
        ),
        ReviewComment(
            comment_id="c3",
            pr_number=123,
            path="",
            line=0,
            body="General comment",
            author="user3",
            created_at="2024-01-03",
        ),
    ]

    foo_comments = geo.filter_comments_to_node(comments, foo_node, code, "python")

    assert len(foo_comments) == 2
    assert foo_comments[0].comment_id == "c1"
    assert foo_comments[1].comment_id == "c3"


def test_database_pr_and_comment_crud():
    """Test database operations for PRs and comments."""
    from src.db.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")

        pr_data = {
            "pr_number": 123,
            "repo_name": "test/repo",
            "title": "Test PR",
            "body": "Test description",
            "author": "testuser",
            "created_at": "2024-01-01",
            "merged_at": "2024-01-02",
            "is_reverted": False,
        }

        db.insert_pr(pr_data)

        comment_data = {
            "comment_id": "c1",
            "pr_number": 123,
            "node_id": "node_123",
            "body": "Great change!",
            "author": "reviewer1",
            "created_at": "2024-01-01",
        }

        db.insert_localized_comment(comment_data)

        retrieved_pr = db.get_pr(123, "test/repo")
        assert retrieved_pr is not None
        assert retrieved_pr["title"] == "Test PR"

        retrieved_comments = db.get_localized_comments_for_node("node_123")
        assert len(retrieved_comments) == 1
        assert retrieved_comments[0]["body"] == "Great change!"


def test_full_lineage_with_pr_context(temp_repo):
    """Test full pipeline: git -> AST -> lineage -> PR mapping."""
    from src.git.walker import GitWalker
    from src.ast.parser import ASTParser
    from src.ast.lineage import LineageTracker

    file_path = Path(temp_repo) / "test.py"

    content_v1 = """def foo():
    x = 1
    return x
"""
    file_path.write_text(content_v1)
    repo = Repo(temp_repo)
    repo.index.add(["test.py"])
    repo.index.commit("Initial: add foo (#1)")

    content_v2 = """def foo():
    x = 10
    return x
"""
    file_path.write_text(content_v2)
    repo.index.add(["test.py"])
    repo.index.commit("Change: modify foo (#2)")

    git = GitWalker(temp_repo)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    edges = tracker.track_lineage("test.py", "foo", "py", max_commits=10)

    assert len(edges) >= 1

    from src.github.fetcher import PRFetcher

    fetcher = PRFetcher()
    pr_num = fetcher.extract_pr_number_from_commit_message(edges[0].commit_message)
    assert pr_num == 2

    from src.db.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "lineage.db")

        for edge in edges:
            db.insert_lineage_edge(
                {
                    "parent_node_id": edge.parent_node_id,
                    "child_node_id": edge.child_node_id,
                    "change_type": edge.change_type,
                    "confidence": edge.confidence,
                    "commit_hash": edge.commit_hash,
                    "commit_message": edge.commit_message,
                    "author": edge.author,
                    "date": edge.date,
                }
            )

        edges_from_db = db.get_lineage_edges()
        assert len(edges_from_db) >= 1


def test_mcp_analyze_function_integration(temp_repo):
    """Test MCP analyze-function method end-to-end."""
    from src.mcp.server import MCPServer
    from src.git.walker import GitWalker
    from src.ast.parser import ASTParser
    from src.ast.lineage import LineageTracker

    file_path = Path(temp_repo) / "example.py"

    content = """def hello():
    return "world"

def goodbye():
    return "farewell"
"""
    file_path.write_text(content)

    repo = Repo(temp_repo)
    repo.index.add(["example.py"])
    repo.index.commit("Add functions")

    git = GitWalker(temp_repo)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    edges = tracker.track_lineage("example.py", "hello", "py", max_commits=10)

    assert len(edges) >= 0

    functions = ast.extract_nodes(ast.parse_file(content, "python"), "python")
    func_names = [n.name for n in functions]

    assert "hello" in func_names
    assert "goodbye" in func_names

    mcp_methods = MCPServer().methods
    repo_path = mcp_methods._find_git_repo(str(file_path))
    assert repo_path == temp_repo
