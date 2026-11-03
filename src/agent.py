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

from .tools import GitHubTools
from .hitl_gate import HITLGate, Action
from .guardrails import enforce_label_vocabulary
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.prompts import SYSTEM_PROMPT, CLASSIFICATION_PROMPT, LABEL_SUGGESTIONS

# Load environment variables
load_dotenv()

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')


class GitHubTriageAgent:
    """ADK-based agent for GitHub issue triage."""
    
    def __init__(self, enable_hitl: bool = True):
        """
        Initialize the agent with API clients.
        
        Args:
            enable_hitl: If True, enable human-in-the-loop approval gate (Phase 2)
        """
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        if not GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN not set in .env")
        if not GITHUB_REPO:
            raise ValueError("GITHUB_REPO not set in .env")
        
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.gh_tools = GitHubTools(GITHUB_TOKEN, GITHUB_REPO)
        self.model = "claude-opus-5-5"
        self.hitl_gate = HITLGate(interactive=enable_hitl) if enable_hitl else None
        self.enable_hitl = enable_hitl
    
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
                # Take everything from the first { to the last }. Splitting on code fences is wrong,
                # because the comment text itself can contain code blocks.
                start = response_text.find("{")
                end = response_text.rfind("}")
                json_str = response_text[start:end + 1] if start != -1 and end > start else response_text
                
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
            
            # Issue number and title come from GitHub, never from the model
            if isinstance(classification, dict):
                classification["issue_number"] = issue["number"]
                classification["issue_title"] = issue["title"]

            classification = enforce_label_vocabulary(classification)
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
    
    def propose_github_action(self, classification: dict) -> None:
        """
        Propose a GitHub action (add labels and/or comment) with HITL approval.
        
        Args:
            classification: Classification result with labels and comment
        """
        if not self.enable_hitl or not self.hitl_gate:
            print("[WARNING] HITL gate not enabled. Skipping approval.")
            return
        
        issue_number = classification.get('issue_number')
        if not issue_number:
            print("[SKIP] Cannot propose action: issue number is null")
            return
        
        # Determine action type
        has_labels = bool(classification.get('suggested_labels'))
        has_comment = bool(classification.get('response_comment'))
        
        if not has_labels and not has_comment:
            print(f"[SKIP] Issue #{issue_number}: No labels or comment to propose")
            return
        
        action_type = 'both' if (has_labels and has_comment) else ('add_labels' if has_labels else 'add_comment')
        
        # Create action
        action = Action(
            issue_number=issue_number,
            issue_title=classification.get('issue_title', 'Unknown'),
            classification=classification.get('classification', 'unknown'),
            action_type=action_type,
            labels=classification.get('suggested_labels', []),
            comment=classification.get('response_comment')
        )
        
        # Propose to gate
        self.hitl_gate.propose_action(action)
    
    def execute_approved_actions(self) -> None:
        """
        Execute all approved actions on GitHub.
        This is the only place where GitHub write operations happen.
        """
        if not self.enable_hitl or not self.hitl_gate:
            print("[WARNING] HITL gate not enabled. Cannot execute actions.")
            return
        
        approved_actions = self.hitl_gate.get_approved_actions()
        
        if not approved_actions:
            print("[INFO] No approved actions to execute.")
            return
        
        print(f"\n[EXECUTE] Writing {len(approved_actions)} approved action(s) to GitHub...\n")
        
        for action in approved_actions:
            print(f"[WRITE] Issue #{action.issue_number}: {action.issue_title}")
            
            # Add labels
            if action.action_type in ['add_labels', 'both']:
                if self.gh_tools.add_label(action.issue_number, action.labels):
                    print(f"  [OK] Added labels: {', '.join(action.labels)}")
                else:
                    print(f"  [ERROR] Failed to add labels")
            
            # Add comment
            if action.action_type in ['add_comment', 'both']:
                if action.comment:
                    if self.gh_tools.add_comment(action.issue_number, action.comment):
                        print(f"  [OK] Added comment ({len(action.comment)} chars)")
                    else:
                        print(f"  [ERROR] Failed to add comment")
        
        # Save approval log
        self.hitl_gate.save_approvals("approval_log.json")
    
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
    """Main entry point for Phase 1 and Phase 2."""
    # Check for flags
    use_demo = '--demo' in sys.argv
    enable_hitl = '--hitl' in sys.argv or '--phase2' in sys.argv
    
    phase = "2 (WITH HITL APPROVAL)" if enable_hitl else "1 (READ-ONLY)"
    
    print(f"[AGENT] GitHub Issue Triage Agent — Phase {phase}")
    print("="*80)
    
    try:
        agent = GitHubTriageAgent(enable_hitl=enable_hitl)
        print(f"[OK] Agent initialized with model: {agent.model}")
        print(f"[OK] HITL approval gate: {'ENABLED' if enable_hitl else 'DISABLED'}\n")
        
        # Process issues
        results = agent.process_issues(limit=5, use_demo=use_demo)
        
        if results:
            # Display results
            agent.display_results(results)
            
            # Phase 2: Propose actions for HITL approval
            if enable_hitl and agent.hitl_gate:
                print("\n" + "="*80)
                print("[PHASE 2] HUMAN-IN-THE-LOOP APPROVAL GATE")
                print("="*80)
                
                # Propose all actions
                for result in results:
                    agent.propose_github_action(result)
                
                # Interactive approval
                print("\n")
                agent.hitl_gate.interactive_approve()
                
                # Execute approved actions
                agent.execute_approved_actions()
            
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