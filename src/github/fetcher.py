import os
import re
from dataclasses import dataclass
from typing import Optional
from github import Github
from github.PullRequest import PullRequest
from github.IssueComment import IssueComment
from github.PullRequestComment import PullRequestComment


@dataclass
class PR:
    number: int
    repo_name: str
    title: str
    body: str
    author: str
    created_at: str
    merged_at: Optional[str]
    is_reverted: bool


@dataclass
class ReviewComment:
    comment_id: str
    pr_number: int
    path: str
    line: int
    body: str
    author: str
    created_at: str


class PRFetcher:
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        if self.github_token:
            self.github = Github(self.github_token)
        else:
            self.github = None

    def extract_pr_number_from_commit_message(self, message: str) -> Optional[int]:
        """Extract PR number from commit message like 'Fix #123' or 'PR #456'"""
        patterns = [
            r"#(\d+)",
            r"PR\s*#?(\d+)",
            r"closes\s+#?(\d+)",
            r"fixes\s+#?(\d+)",
            r"resolves\s+#?(\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def get_pr_from_commit(
        self, repo_name: str, commit_hash: str, commit_message: str
    ) -> Optional[PR]:
        """Get PR associated with a commit."""
        if not self.github:
            return None

        pr_number = self.extract_pr_number_from_commit_message(commit_message)
        if not pr_number:
            return None

        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            return PR(
                number=pr.number,
                repo_name=repo_name,
                title=pr.title,
                body=pr.body or "",
                author=pr.user.login,
                created_at=pr.created_at.isoformat(),
                merged_at=pr.merged_at.isoformat() if pr.merged_at else None,
                is_reverted=self._check_if_reverted(pr, repo),
            )
        except Exception:
            return None

    def _check_if_reverted(self, pr: PullRequest, repo) -> bool:
        """Check if a PR was reverted by looking at later PRs."""
        try:
            # Check if there's a PR that reverts this one
            search_query = f"revert {pr.number} repo:{repo.full_name}"
            issues = self.github.search_issues(search_query)
            return issues.totalCount > 0
        except Exception:
            return False

    def get_review_comments(
        self, repo_name: str, pr_number: int
    ) -> list[ReviewComment]:
        """Get all review comments for a PR."""
        if not self.github:
            return []

        comments = []

        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            # Get review comments
            for comment in pr.get_comments():
                comments.append(
                    ReviewComment(
                        comment_id=str(comment.id),
                        pr_number=pr_number,
                        path=comment.path,
                        line=comment.line or comment.original_line,
                        body=comment.body or "",
                        author=comment.user.login,
                        created_at=comment.created_at.isoformat(),
                    )
                )

            # Get review thread comments
            for review in pr.get_reviews():
                for comment in review.body.split("\n"):
                    if comment.strip():
                        pass

        except Exception:
            pass

        return comments

    def get_all_comments(self, repo_name: str, pr_number: int) -> list[ReviewComment]:
        """Get all comments (review comments + issue comments) for a PR."""
        if not self.github:
            return []

        comments = []

        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            # Review comments
            for comment in pr.get_comments():
                comments.append(
                    ReviewComment(
                        comment_id=f"review_{comment.id}",
                        pr_number=pr_number,
                        path=comment.path,
                        line=comment.line or comment.original_line,
                        body=comment.body or "",
                        author=comment.user.login,
                        created_at=comment.created_at.isoformat(),
                    )
                )

            # Issue comments (general discussion)
            for comment in pr.get_issue_comments():
                comments.append(
                    ReviewComment(
                        comment_id=f"issue_{comment.id}",
                        pr_number=pr_number,
                        path="",
                        line=0,
                        body=comment.body or "",
                        author=comment.user.login,
                        created_at=comment.created_at.isoformat(),
                    )
                )

        except Exception:
            pass

        return comments
