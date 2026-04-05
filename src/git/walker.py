import os
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from git import Repo, GitCommandError
from git.diff import DiffIndex


@dataclass
class Commit:
    hash: str
    author: str
    author_email: str
    date: str
    message: str
    parent_hashes: list[str]


@dataclass
class FileMove:
    old_path: str
    new_path: str
    commit_hash: str


@dataclass
class DiffHunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    deleted_lines: list[int]
    added_lines: list[int]


class GitWalker:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self.repo = Repo(repo_path)

    def get_commits_for_file(
        self, file_path: str, max_count: Optional[int] = None
    ) -> list[Commit]:
        """Get commits that touched a file, in reverse chronological order."""
        commits = []

        try:
            for i, commit in enumerate(self.repo.iter_commits(paths=file_path)):
                if max_count and i >= max_count:
                    break

                parent_hashes = (
                    [p.hexsha for p in commit.parents] if commit.parents else []
                )

                commits.append(
                    Commit(
                        hash=commit.hexsha,
                        author=commit.author.name,
                        author_email=commit.author.email,
                        date=commit.authored_datetime.isoformat(),
                        message=commit.message.strip(),
                        parent_hashes=parent_hashes,
                    )
                )

        except Exception:
            pass

        return commits

    def get_diff_for_commit(
        self, commit_hash: str, file_path: str, parent_hash: Optional[str] = None
    ) -> list[DiffHunk]:
        """Get diff hunks for a specific commit and file.

        Uses --no-renames to force raw deletions/additions for accurate line tracking.
        """
        git = self.repo.git()
        hunks = []

        try:
            if parent_hash:
                diff_output = git.diff(
                    "--no-renames", "-U10", parent_hash, commit_hash, "--", file_path
                )
            else:
                diff_output = git.diff(
                    "--no-renames", "-U10", commit_hash, "--", file_path
                )

            hunks = self._parse_diff(diff_output)

        except GitCommandError:
            pass

        return hunks

    def get_commit_parent(self, commit_hash: str) -> Optional[str]:
        """Get the parent commit hash for a given commit."""
        try:
            commit = self.repo.commit(commit_hash)
            if commit.parents:
                return commit.parents[0].hexsha
        except Exception:
            pass
        return None

    def _parse_diff(self, diff_output: str) -> list[DiffHunk]:
        """Parse unified diff output into structured hunks."""
        if not diff_output:
            return []

        hunks = []
        current_hunk = None
        deleted_lines = []
        added_lines = []

        in_hunk = False
        old_start, old_lines, new_start, new_lines = 0, 0, 0, 0

        for line in diff_output.split("\n"):
            if line.startswith("@@"):
                if current_hunk and (deleted_lines or added_lines):
                    current_hunk = DiffHunk(
                        old_start=old_start,
                        old_lines=old_lines,
                        new_start=new_start,
                        new_lines=new_lines,
                        deleted_lines=deleted_lines.copy(),
                        added_lines=added_lines.copy(),
                    )
                    hunks.append(current_hunk)

                match = line[4:].rstrip(" ").split("@@")
                if len(match) >= 2:
                    old_info = match[0].split()
                    new_info = match[1].split()

                    try:
                        old_start = 1
                        old_lines = 1
                        new_start = 1
                        new_lines = 1

                        if old_info:
                            old_start_str = old_info[0].lstrip("-")
                            old_start = (
                                int(old_start_str.split(",")[0])
                                if old_start_str.isdigit()
                                else 1
                            )
                        if len(old_info) > 1:
                            old_lines_str = old_info[1].lstrip(",+")
                            old_lines = (
                                int(old_lines_str.split(",")[0])
                                if old_lines_str.isdigit()
                                else 1
                            )

                        if new_info:
                            new_start_str = new_info[0].lstrip("+")
                            new_start = (
                                int(new_start_str.split(",")[0])
                                if new_start_str.isdigit()
                                else 1
                            )
                        if len(new_info) > 1:
                            new_lines_str = new_info[1].lstrip(",+")
                            new_lines = (
                                int(new_lines_str.split(",")[0])
                                if new_lines_str.isdigit()
                                else 1
                            )
                    except (ValueError, IndexError):
                        old_start = 1
                        old_lines = 1
                        new_start = 1
                        new_lines = 1

                deleted_lines = []
                added_lines = []
                in_hunk = True

            elif in_hunk and line.startswith("-") and not line.startswith("---"):
                deleted_lines.append(old_start + len(deleted_lines))
                old_start += 1

            elif in_hunk and line.startswith("+") and not line.startswith("+++"):
                added_lines.append(new_start + len(added_lines))
                new_start += 1

        if current_hunk and (deleted_lines or added_lines):
            current_hunk = DiffHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                deleted_lines=deleted_lines.copy(),
                added_lines=added_lines.copy(),
            )
            hunks.append(current_hunk)

        return hunks

    def get_file_at_commit(self, commit_hash: str, file_path: str) -> Optional[str]:
        """Get file content at a specific commit."""
        try:
            blob = self.repo.tree(commit_hash)[file_path]
            return blob.data_stream.read().decode("utf-8")
        except KeyError:
            return None

    def get_file_moves(self, file_path: str) -> list[FileMove]:
        """Detect file renames/moves using git log --follow."""
        moves = []
        git = self.repo.git()

        try:
            output = git.log(
                "--diff-filter=R", "--format=%H|%s", "--follow", "--", file_path
            )

            for line in output.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) < 2:
                    continue

                commit_hash = parts[0]
                message = parts[1]

                if " -> " in message:
                    old_path, new_path = message.split(" -> ")
                    moves.append(
                        FileMove(
                            old_path=old_path,
                            new_path=new_path,
                            commit_hash=commit_hash,
                        )
                    )

        except GitCommandError:
            pass

        return moves

    def get_current_file_path(self, target_path: str, commit_hash: str) -> str:
        """Given a target path, find its actual path at the given commit."""
        try:
            tree = self.repo.tree(commit_hash)
            for item in tree.traverse():
                if item.type == "blob":
                    blob_path = str(item.path)
                    if blob_path.endswith(target_path) or target_path in blob_path:
                        return blob_path
        except Exception:
            pass
        return target_path

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute deterministic hash of code content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
