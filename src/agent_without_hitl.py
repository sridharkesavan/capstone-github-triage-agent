"""
Phase 1: Local ADK Agent for GitHub Issue Triage

This agent:
1. Fetches open issues from a GitHub repository
2. Classifies them (bug/feature/question/duplicate)
3. Proposes labels and response comments
4. DOES NOT write to GitHub (Phase 2 adds HITL approval gate)

Usage:
    python -m src.agent
"""

import os
import json
import sys
from dotenv import load_dotenv
from anthropic import Anthropic

from src.tools import GitHubTools
from config.prompts import SYSTEM_PROMPT, CLASSIFICATION_PROMPT, LABEL_SUGGESTIONS

# Load environment variables
load_dotenv()

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')


class GitHubTriageAgent:
    """ADK-based agent for GitHub issue triage."""
    
    def __init__(self):
        """Initialize the agent with API clients."""
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        if not GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN not set in .env")
        if not GITHUB_REPO:
            raise ValueError("GITHUB_REPO not set in .env")
        
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.gh_tools = GitHubTools(GITHUB_TOKEN, GITHUB_REPO)
        self.model = "claude-opus-5-5"
    
    def _get_demo_issues(self) -> list[dict]:
        """
        Return demo issues for testing when repo has no real issues.
        
        Returns:
            List of demo issue dictionaries
        """
        return [
            {
                'number': 1,
                'title': 'Agent crashes when processing empty issues list',
                'body': 'When I run the agent on a repo with no issues, it throws an IndexError. The error trace is attached.',
                'author': 'test-user',
                'created_at': '2026-10-11T00:00:00',
                'labels': [],
                'url': 'https://github.com/example/repo/issues/1',
            },
            {
                'number': 2,
                'title': 'Add support for custom label templates',
                'body': 'Users should be able to define custom label schemas for different project types.',
                'author': 'feature-requester',
                'created_at': '2026-10-11T01:00:00',
                'labels': [],
                'url': 'https://github.com/example/repo/issues/2',
            },
            {
                'number': 3,
                'title': 'How do I integrate this with GitHub Actions?',
                'body': 'Can you provide an example of running this agent as part of a CI/CD pipeline?',
                'author': 'docs-user',
                'created_at': '2026-10-11T02:00:00',
                'labels': [],
                'url': 'https://github.com/example/repo/issues/3',
            },
        ]
    
    def classify_issue(self, issue: dict) -> dict:
        """
        Classify a single issue using Claude.
        
        Args:
            issue: Issue dictionary with number, title, body
            
        Returns:
            Classification result with labels and suggested response
        """
        prompt = CLASSIFICATION_PROMPT.format(
            title=issue['title'],
            body=issue['body'][:500]  # Limit body to first 500 chars for context
        )
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Handle extended thinking (Claude Opus 5.5 returns ThinkingBlock + TextBlock)
            response_text = None
            for block in response.content:
                # Get the text block (skip ThinkingBlock)
                if hasattr(block, 'text'):
                    response_text = block.text
                    break
            
            if not response_text:
                raise ValueError("No text block found in response")
            
            # Try to extract JSON from the response
            try:
                # Handle case where response is wrapped in markdown code blocks
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0].strip()
                else:
                    json_str = response_text
                
                classification = json.loads(json_str)
            except (json.JSONDecodeError, IndexError) as e:
                print(f"⚠ Failed to parse JSON response: {e}")
                print(f"Raw response: {response_text}")
                # Return a fallback classification
                classification = {
                    "issue_number": issue['number'],
                    "issue_title": issue['title'],
                    "classification": "question",
                    "confidence": 0.5,
                    "suggested_labels": ["needs-triage"],
                    "response_comment": "Thank you for opening this issue. We'll review it soon.",
                    "reasoning": "Default classification due to parsing error"
                }
            
            return classification
        
        except Exception as e:
            print(f"✗ Error classifying issue #{issue['number']}: {e}")
            return {
                "issue_number": issue['number'],
                "issue_title": issue['title'],
                "classification": "question",
                "confidence": 0.0,
                "suggested_labels": ["needs-triage"],
                "response_comment": None,
                "reasoning": f"Error: {str(e)}"
            }
    
    def process_issues(self, limit: int = 5, use_demo: bool = False) -> list[dict]:
        """
        Fetch and classify recent open issues.
        
        Args:
            limit: Maximum number of issues to process
            use_demo: If True, use demo issues for testing
            
        Returns:
            List of classification results
        """
        if use_demo:
            print(f"\n[DEMO] Using demo issues for testing (no real issues found)...")
            issues = self._get_demo_issues()
        else:
            print(f"\n[FETCH] Fetching up to {limit} open issues from {GITHUB_REPO}...")
            issues = self.gh_tools.get_open_issues(limit=limit)
        
        if not issues:
            print("[INFO] No open issues found. Run with --demo flag to test with sample issues.")
            return []
        
        print(f"[OK] Found {len(issues)} issue(s). Classifying...\n")
        
        results = []
        for i, issue in enumerate(issues, 1):
            print(f"[{i}/{len(issues)}] Processing issue #{issue['number']}: {issue['title'][:50]}...")
            classification = self.classify_issue(issue)
            results.append(classification)
            print(f"  -> Classification: {classification['classification'].upper()}")
            print(f"  -> Confidence: {classification['confidence']:.1%}")
            print(f"  -> Labels: {', '.join(classification['suggested_labels'])}")
            print()
        
        return results
    
    def display_results(self, results: list[dict]) -> None:
        """
        Display triage results in a readable format.
        
        Args:
            results: List of classification results
        """
        print("\n" + "="*80)
        print("[RESULTS] GITHUB ISSUE TRIAGE — PHASE 1 (READ-ONLY, NO WRITES YET)")
        print("="*80 + "\n")
        
        for result in results:
            print(f"Issue #{result['issue_number']}: {result['issue_title']}")
            print(f"  Classification: {result['classification'].upper()} ({result['confidence']:.1%} confidence)")
            print(f"  Suggested labels: {', '.join(result['suggested_labels'])}")
            if result['response_comment']:
                print(f"  Suggested comment: {result['response_comment']}")
            print(f"  Reasoning: {result['reasoning']}")
            print()
        
        print("="*80)
        print("[DONE] Phase 1 complete. No changes written to GitHub yet.")
        print("[TODO] Phase 2 will add a human-in-the-loop approval gate.")
        print("="*80)
    
    def save_results(self, results: list[dict], filename: str = "triage_results.json") -> None:
        """
        Save classification results to a JSON file.
        
        Args:
            results: List of classification results
            filename: Output filename
        """
        try:
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"[OK] Results saved to {filename}")
        except Exception as e:
            print(f"[ERROR] Error saving results: {e}")


def main():
    """Main entry point for Phase 1."""
    print("[AGENT] GitHub Issue Triage Agent — Phase 1 (Local, Read-Only)")
    print("="*80)
    
    # Check for --demo flag
    use_demo = '--demo' in sys.argv
    
    try:
        agent = GitHubTriageAgent()
        print(f"[OK] Agent initialized with model: {agent.model}\n")
        
        # Process issues
        results = agent.process_issues(limit=5, use_demo=use_demo)
        
        if results:
            # Display results
            agent.display_results(results)
            
            # Save results
            agent.save_results(results)
        else:
            print("No issues to process.")
    
    except KeyError as e:
        print(f"[ERROR] Missing environment variable: {e}")
        print("Please ensure .env file contains: ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_REPO")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()