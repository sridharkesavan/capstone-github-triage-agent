"""
GitHub API tools for the issue triage agent.
"""

import json
from typing import Optional
from github import Github
from github.GithubException import GithubException


from src.hitl_gate import Action


class UnapprovedActionError(Exception):
    """Raised when a GitHub write is attempted without an approved Action that covers it."""


class GitHubTools:
    """Wrapper around PyGithub for issue triage operations."""
    
    def __init__(self, token: str, repo_name: str):
        """
        Initialize GitHub client.
        
        Args:
            token: GitHub personal access token
            repo_name: Repository name (format: owner/repo)
        """
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)
        print(f"[OK] Connected to {repo_name}")
    
    def get_open_issues(self, limit: int = 10) -> list[dict]:
        """
        Fetch recent open issues from the repository.
        
        Args:
            limit: Maximum number of issues to fetch (default 10)
            
        Returns:
            List of issue dictionaries with metadata
        """
        try:
            # Fetch issues explicitly (excludes PRs by default with type='issues')
            issues = self.repo.get_issues(state='open', sort='created', direction='desc')
            result = []
            
            count = 0
            total_checked = 0
            for issue in issues:
                total_checked += 1
                if count >= limit:
                    break
                
                # Skip pull requests (sometimes they slip through)
                if issue.pull_request:
                    continue
                
                result.append({
                    'number': issue.number,
                    'title': issue.title,
                    'body': issue.body or '',
                    'author': issue.user.login,
                    'created_at': issue.created_at.isoformat(),
                    'labels': [label.name for label in issue.labels],
                    'url': issue.html_url,
                })
                count += 1
            
            print(f"[DEBUG] Fetched {count} issues (checked {total_checked})")
            return result
        except GithubException as e:
            print(f"[ERROR] Error fetching issues: {e}")
            return []
    
    def get_issue(self, issue_number: int) -> Optional[dict]:
        """
        Fetch a specific issue by number.
        
        Args:
            issue_number: GitHub issue number
            
        Returns:
            Issue dictionary or None if not found
        """
        try:
            issue = self.repo.get_issue(issue_number)
            return {
                'number': issue.number,
                'title': issue.title,
                'body': issue.body or '',
                'author': issue.user.login,
                'created_at': issue.created_at.isoformat(),
                'labels': [label.name for label in issue.labels],
                'url': issue.html_url,
            }
        except GithubException as e:
            print(f"[ERROR] Error fetching issue #{issue_number}: {e}")
            return None
    
    def _add_label(self, issue_number: int, labels: list[str]) -> bool:
        """
        Add labels to an issue (requires approval in Phase 2).
        
        Args:
            issue_number: GitHub issue number
            labels: List of label names to add
            
        Returns:
            True if successful, False otherwise
        """
        try:
            issue = self.repo.get_issue(issue_number)
            issue.add_to_labels(*labels)
            print(f"[OK] Added labels {labels} to issue #{issue_number}")
            return True
        except GithubException as e:
            print(f"[ERROR] Error adding labels: {e}")
            return False
    
    def _add_comment(self, issue_number: int, comment: str) -> bool:
        """
        Add a comment to an issue (requires approval in Phase 2).
        
        Args:
            issue_number: GitHub issue number
            comment: Comment text
            
        Returns:
            True if successful, False otherwise
        """
        try:
            issue = self.repo.get_issue(issue_number)
            issue.create_comment(comment)
            print(f"[OK] Added comment to issue #{issue_number}")
            return True
        except GithubException as e:
            print(f"[ERROR] Error adding comment: {e}")
            return False
    
    @staticmethod
    def _require_approved(action, needs: str) -> None:
        """Refuse unless this is an approved Action that covers the write ('labels' or 'comment')."""
        if not isinstance(action, Action):
            raise UnapprovedActionError(f"expected an Action, got {type(action).__name__}")
        if action.approved is not True:
            raise UnapprovedActionError(
                f"action {action.id} for issue #{action.issue_number} is not approved"
            )
        if needs == "labels" and not (action.action_type in ("add_labels", "both") and action.labels):
            raise UnapprovedActionError(f"action {action.id} was not approved to add labels")
        if needs == "comment" and not (action.action_type in ("add_comment", "both") and action.comment):
            raise UnapprovedActionError(f"action {action.id} was not approved to add a comment")

    def apply_labels(self, action) -> bool:
        """Add the labels of an approved Action to its issue. Raises UnapprovedActionError otherwise."""
        self._require_approved(action, "labels")
        return self._add_label(action.issue_number, action.labels)

    def post_comment(self, action) -> bool:
        """Post the comment of an approved Action on its issue. Raises UnapprovedActionError otherwise."""
        self._require_approved(action, "comment")
        return self._add_comment(action.issue_number, action.comment)

    def get_existing_labels(self) -> list[str]:
        """
        Fetch all existing labels in the repository.
        
        Returns:
            List of label names
        """
        try:
            labels = self.repo.get_labels()
            return [label.name for label in labels]
        except GithubException as e:
            print(f"[ERROR] Error fetching labels: {e}")
            return []