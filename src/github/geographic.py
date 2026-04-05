from dataclasses import dataclass
from typing import Optional

from ..ast.parser import ASTParser, ASTNode
from ..github.fetcher import ReviewComment


@dataclass
class LocalizedComment:
    comment_id: str
    pr_number: int
    node_id: str
    body: str
    author: str
    created_at: str


class GeographicFilter:
    """Filter review comments to only those targeting specific AST nodes."""

    def __init__(self, ast_parser: ASTParser):
        self.ast = ast_parser

    def filter_comments_to_node(
        self,
        comments: list[ReviewComment],
        node: ASTNode,
        commit_content: str,
        language: str,
    ) -> list[LocalizedComment]:
        """Filter comments to only those within the node's line boundaries."""
        localized = []

        for comment in comments:
            if comment.line == 0 or not comment.path:
                localized.append(
                    LocalizedComment(
                        comment_id=comment.comment_id,
                        pr_number=comment.pr_number,
                        node_id=node.node_id,
                        body=comment.body,
                        author=comment.author,
                        created_at=comment.created_at,
                    )
                )
                continue

            if self._is_comment_in_node(comment.line, node):
                localized.append(
                    LocalizedComment(
                        comment_id=comment.comment_id,
                        pr_number=comment.pr_number,
                        node_id=node.node_id,
                        body=comment.body,
                        author=comment.author,
                        created_at=comment.created_at,
                    )
                )

        return localized

    def _is_comment_in_node(self, comment_line: int, node: ASTNode) -> bool:
        """Check if a comment line falls within the AST node's boundaries."""
        return node.start_line <= comment_line <= node.end_line

    def get_node_at_line(
        self, commit_content: str, language: str, line_number: int
    ) -> Optional[ASTNode]:
        """Find the AST node containing a specific line number."""
        tree = self.ast.parse_file(commit_content, language)
        if not tree:
            return None

        return self.ast.find_node_at_line(tree, language, line_number)

    def filter_comments_to_lineage(
        self,
        comments: list[ReviewComment],
        lineage_nodes: list[tuple[ASTNode, str]],
        language: str,
    ) -> list[LocalizedComment]:
        """Filter comments to nodes in the lineage chain."""
        all_localized = []

        for node, commit_content in lineage_nodes:
            localized = self.filter_comments_to_node(
                comments, node, commit_content, language
            )
            all_localized.extend(localized)

        return all_localized
