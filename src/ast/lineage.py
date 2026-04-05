import re
from dataclasses import dataclass
from typing import Optional

from ..git.walker import GitWalker, DiffHunk
from ..ast.parser import ASTParser


@dataclass
class LineageEdge:
    parent_node_id: str
    child_node_id: str
    change_type: str
    confidence: float
    commit_hash: str = ""
    commit_message: str = ""


class LineageTracker:
    """Four-tier lineage detection for AST nodes across commits."""

    def __init__(self, git_walker: GitWalker, ast_parser: ASTParser):
        self.git = git_walker
        self.ast = ast_parser

    def track_lineage(
        self, file_path: str, function_name: str, language: str, max_commits: int = 100
    ) -> list[LineageEdge]:
        """Track lineage of a function across git history."""
        commits = self.git.get_commits_for_file(file_path, max_count=max_commits)
        if not commits:
            return []

        commits = list(reversed(commits))

        edges = []
        previous_node = None
        previous_content = None
        previous_start_line = None

        for commit in commits:
            content = self.git.get_file_at_commit(commit.hash, file_path)
            if not content:
                continue

            tree = self.ast.parse_file(content, language)
            if not tree:
                continue

            current_node = self.ast.find_node_by_name(tree, language, function_name)
            if not current_node:
                continue

            if previous_node and previous_content and previous_start_line is not None:
                edge = self._detect_edge_type(
                    previous_content,
                    current_node.content,
                    previous_start_line,
                    current_node.start_line,
                    previous_node.name,
                    current_node.name,
                    previous_node.node_id,
                    current_node.node_id,
                    commit.hash,
                    file_path,
                )
                if edge:
                    edge.commit_hash = commit.hash
                    edge.commit_message = commit.message
                    edges.append(edge)

            previous_node = current_node
            previous_content = current_node.content
            previous_start_line = current_node.start_line

        return edges

    def _detect_edge_type(
        self,
        old_content: str,
        new_content: str,
        old_start_line: int,
        new_start_line: int,
        old_name: str,
        new_name: str,
        parent_id: str,
        child_id: str,
        commit_hash: str,
        file_path: str,
    ) -> Optional[LineageEdge]:
        """Determine lineage edge type using four-tier hierarchy."""

        tier1 = self._tier1_identity(old_content, new_content, parent_id, child_id)
        if tier1:
            return tier1

        parent_commit = self.git.get_commit_parent(commit_hash)
        if parent_commit:
            diffs = self.git.get_diff_for_commit(commit_hash, file_path, parent_commit)
            if diffs:
                tier2 = self._tier2_physical(
                    old_start_line, new_start_line, diffs, parent_id, child_id
                )
                if tier2:
                    return tier2

        tier3 = self._tier3_signature(
            old_name, new_name, old_content, new_content, parent_id, child_id
        )
        if tier3:
            return tier3

        tier4 = self._tier4_semantic(old_content, new_content, parent_id, child_id)
        if tier4:
            return tier4

        return None

    def _tier1_identity(
        self, old_content: str, new_content: str, parent_id: str, child_id: str
    ) -> Optional[LineageEdge]:
        """Tier 1: Global hash check for identical code."""
        old_hash = self.git.compute_content_hash(old_content.strip())
        new_hash = self.git.compute_content_hash(new_content.strip())

        if old_hash == new_hash:
            return LineageEdge(
                parent_node_id=parent_id,
                child_node_id=child_id,
                change_type="identity",
                confidence=1.0,
            )
        return None

    def _tier2_physical(
        self,
        old_start_line: int,
        new_start_line: int,
        diffs: list[DiffHunk],
        parent_id: str,
        child_id: str,
    ) -> Optional[LineageEdge]:
        """Tier 2: Physical intersection via diff math."""
        deleted = []
        added = []
        for diff in diffs:
            deleted.extend(diff.deleted_lines)
            added.extend(diff.added_lines)

        line_shift = 0
        for ln in added:
            if ln < old_start_line:
                line_shift += 1
        for ln in deleted:
            if ln < old_start_line:
                line_shift -= 1

        projected = old_start_line + line_shift
        if abs(projected - new_start_line) <= 2:
            return LineageEdge(
                parent_node_id=parent_id,
                child_node_id=child_id,
                change_type="physical",
                confidence=0.85,
            )
        return None

    def _tier3_signature(
        self,
        old_name: str,
        new_name: str,
        old_content: str,
        new_content: str,
        parent_id: str,
        child_id: str,
    ) -> Optional[LineageEdge]:
        """Tier 3: Signature match - name unchanged, content cut-and-paste."""
        if old_name == new_name:
            overlap = self._jaccard_similarity(
                set(old_content.split()), set(new_content.split())
            )
            if 0.5 <= overlap:
                return LineageEdge(
                    parent_node_id=parent_id,
                    child_node_id=child_id,
                    change_type="signature",
                    confidence=overlap,
                )
        return None

    def _tier4_semantic(
        self, old_content: str, new_content: str, parent_id: str, child_id: str
    ) -> Optional[LineageEdge]:
        """Tier 4: Semantic overlap - Jaccard for split/merge."""
        overlap = self._jaccard_similarity(
            set(old_content.split()), set(new_content.split())
        )
        if overlap >= 0.5:
            return LineageEdge(
                parent_node_id=parent_id,
                child_node_id=child_id,
                change_type="semantic",
                confidence=overlap,
            )
        return None

    def _jaccard_similarity(self, set1: set, set2: set) -> float:
        """Calculate Jaccard similarity between two sets."""
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0
