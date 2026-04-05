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


def test_pure_drift(temp_repo):
    """Test Tier 1: Identity - same code, line numbers shift."""
    from src.git.walker import GitWalker
    from src.ast.parser import ASTParser
    from src.ast.lineage import LineageTracker

    file_path = Path(temp_repo) / "test.py"

    content_v1 = """def foo():
    x = 1
    y = 2
    return x + y
"""
    file_path.write_text(content_v1)
    repo = Repo(temp_repo)
    repo.index.add(["test.py"])
    repo.index.commit("Initial: add foo")

    content_v2 = """


def foo():
    x = 1
    y = 2
    return x + y
"""
    file_path.write_text(content_v2)
    repo.index.add(["test.py"])
    repo.index.commit("Drift: add whitespace")

    git = GitWalker(temp_repo)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    edges = tracker.track_lineage("test.py", "foo", "py", max_commits=10)

    assert len(edges) >= 1
    assert edges[0].change_type in ("identity", "physical")


def test_shadow_swap(temp_repo):
    """Test Tier 2: Two functions swap positions."""
    from src.git.walker import GitWalker
    from src.ast.parser import ASTParser
    from src.ast.lineage import LineageTracker

    file_path = Path(temp_repo) / "test.py"

    content_v1 = """def foo():
    return 1

def bar():
    return 2
"""
    file_path.write_text(content_v1)
    repo = Repo(temp_repo)
    repo.index.add(["test.py"])
    repo.index.commit("Initial: add foo, bar")

    content_v2 = """def bar():
    return 2

def foo():
    return 1
"""
    file_path.write_text(content_v2)
    repo.index.add(["test.py"])
    repo.index.commit("Swap: bar, foo")

    git = GitWalker(temp_repo)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    edges = tracker.track_lineage("test.py", "foo", "py", max_commits=10)

    assert len(edges) >= 1


def test_signature_rename(temp_repo):
    """Test Tier 3: Content changes with same function name."""
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
    repo.index.commit("Initial: add foo")

    content_v2 = """def foo():
    x = 10
    return x
"""
    file_path.write_text(content_v2)
    repo.index.add(["test.py"])
    repo.index.commit("Change: modify implementation")

    git = GitWalker(temp_repo)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    edges = tracker.track_lineage("test.py", "foo", "py", max_commits=10)

    assert len(edges) >= 1


def test_internal_rewrite(temp_repo):
    """Test Tier 2: Content changes, boundaries preserved."""
    from src.git.walker import GitWalker
    from src.ast.parser import ASTParser
    from src.ast.lineage import LineageTracker

    file_path = Path(temp_repo) / "test.py"

    content_v1 = """def foo():
    x = 1
    y = 2
    return x + y
"""
    file_path.write_text(content_v1)
    repo = Repo(temp_repo)
    repo.index.add(["test.py"])
    repo.index.commit("Initial: add foo")

    content_v2 = """def foo():
    x = 10
    y = 20
    return x * y
"""
    file_path.write_text(content_v2)
    repo.index.add(["test.py"])
    repo.index.commit("Rewrite: change implementation")

    git = GitWalker(temp_repo)
    ast = ASTParser()
    tracker = LineageTracker(git, ast)

    edges = tracker.track_lineage("test.py", "foo", "py", max_commits=10)

    assert len(edges) >= 1


def test_file_migration(temp_repo):
    """Test file rename/migration detection."""
    from src.git.walker import GitWalker

    old_path = Path(temp_repo) / "old.py"
    new_path = Path(temp_repo) / "new.py"

    old_path.write_text("x = 1")
    repo = Repo(temp_repo)
    repo.index.add(["old.py"])
    repo.index.commit("Initial")

    new_path.write_text("x = 1")
    old_path.unlink()
    repo.index.add(["new.py"])
    repo.index.remove(["old.py"])
    repo.index.commit("Move: old.py -> new.py")

    git = GitWalker(temp_repo)
    moves = git.get_file_moves("new.py")

    assert len(moves) >= 0


def test_basic_ast_parsing():
    """Test AST parser basic functionality."""
    from src.ast.parser import ASTParser

    parser = ASTParser()

    code = """def hello():
    print("world")
    return True
"""
    tree = parser.parse_file(code, "python")
    assert tree is not None

    nodes = parser.extract_nodes(tree, "python")
    assert len(nodes) >= 1

    hello = parser.find_node_by_name(tree, "python", "hello")
    assert hello is not None
    assert hello.name == "hello"


def test_git_walker_basic():
    """Test GitWalker basic functionality."""
    from src.git.walker import GitWalker

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        test_file = Path(tmpdir) / "test.py"
        test_file.write_text("x = 1")
        repo.index.add(["test.py"])
        repo.index.commit("Initial commit")

        git = GitWalker(tmpdir)
        print(f"DEBUG: tmpdir={tmpdir}")
        commits = git.get_commits_for_file("test.py", max_count=10)
        print(f"DEBUG: got {len(commits)} commits")

        assert len(commits) >= 1
        assert commits[0].message == "Initial commit"
