"""
Phase 2: Human-in-the-Loop (HITL) Approval Gate

Before the agent writes ANYTHING to GitHub, a human must approve it first.
This gate is structurally enforced — the agent cannot bypass it.
"""

import json
from typing import Optional, Literal


class Action:
    """Represents a proposed action (label, comment) on a GitHub issue."""
    
    def __init__(self, 
                 issue_number: int,
                 issue_title: str,
                 classification: str,
                 action_type: Literal['add_labels', 'add_comment', 'both'],
                 labels: list[str],
                 comment: Optional[str] = None):
        """
        Initialize an action proposal.
        
        Args:
            issue_number: GitHub issue number
            issue_title: Issue title for display
            classification: Issue classification (bug/feature/question/duplicate)
            action_type: Type of action (add_labels, add_comment, or both)
            labels: List of labels to add
            comment: Optional comment text to add
        """
        self.issue_number = issue_number
        self.issue_title = issue_title
        self.classification = classification
        self.action_type = action_type
        self.labels = labels
        self.comment = comment
        self.approved = False
        self.approval_note = None
    
    def display(self) -> str:
        """Return a formatted display of the proposed action."""
        display = f"""
[PROPOSED ACTION] Issue #{self.issue_number}: {self.issue_title}

Classification: {self.classification.upper()}

Proposed Actions:
"""
        if self.action_type in ['add_labels', 'both']:
            display += f"  - Add labels: {', '.join(self.labels)}\n"
        
        if self.action_type in ['add_comment', 'both']:
            if self.comment:
                comment_preview = self.comment[:200].replace('\n', ' ') + ('...' if len(self.comment) > 200 else '')
                display += f"  - Add comment: \"{comment_preview}\"\n"
        
        return display
    
    def __repr__(self) -> str:
        return f"<Action issue=#{self.issue_number} type={self.action_type} approved={self.approved}>"


class HITLGate:
    """Human-in-the-Loop approval gate for GitHub write operations."""
    
    def __init__(self, interactive: bool = True):
        """
        Initialize the HITL gate.
        
        Args:
            interactive: If True, prompt user for approval. If False, require explicit approval calls.
        """
        self.interactive = interactive
        self.pending_actions: list[Action] = []
        self.approved_actions: list[Action] = []
        self.rejected_actions: list[Action] = []
    
    def propose_action(self, action: Action) -> None:
        """
        Propose an action for human approval.
        
        Args:
            action: The action to propose
        """
        self.pending_actions.append(action)
        print(action.display())
    
    def approve_action(self, action_index: int, note: str = "") -> bool:
        """
        Approve a proposed action by index.
        
        Args:
            action_index: Index of the action to approve (0-based)
            note: Optional approval note
            
        Returns:
            True if approved, False if index invalid
        """
        if 0 <= action_index < len(self.pending_actions):
            action = self.pending_actions.pop(action_index)
            action.approved = True
            action.approval_note = note
            self.approved_actions.append(action)
            print(f"[APPROVED] Issue #{action.issue_number}: {action.action_type}")
            return True
        return False
    
    def reject_action(self, action_index: int, reason: str = "") -> bool:
        """
        Reject a proposed action by index.
        
        Args:
            action_index: Index of the action to reject (0-based)
            reason: Optional reason for rejection
            
        Returns:
            True if rejected, False if index invalid
        """
        if 0 <= action_index < len(self.pending_actions):
            action = self.pending_actions.pop(action_index)
            action.approval_note = reason
            self.rejected_actions.append(action)
            print(f"[REJECTED] Issue #{action.issue_number}: {reason or 'No reason provided'}")
            return True
        return False
    
    def get_pending_actions(self) -> list[Action]:
        """Return list of pending actions awaiting approval."""
        return self.pending_actions.copy()
    
    def get_approved_actions(self) -> list[Action]:
        """Return list of approved actions."""
        return self.approved_actions.copy()
    
    def get_rejected_actions(self) -> list[Action]:
        """Return list of rejected actions."""
        return self.rejected_actions.copy()
    
    def display_pending(self) -> None:
        """Display all pending actions."""
        if not self.pending_actions:
            print("[INFO] No pending actions.")
            return
        
        print("\n" + "="*80)
        print(f"[PENDING APPROVAL] {len(self.pending_actions)} action(s) waiting for approval")
        print("="*80)
        
        for i, action in enumerate(self.pending_actions):
            print(f"\n[{i}] Issue #{action.issue_number}: {action.issue_title}")
            print(f"    Classification: {action.classification.upper()}")
            print(f"    Action type: {action.action_type}")
            if action.labels:
                print(f"    Labels: {', '.join(action.labels)}")
            if action.comment:
                comment_preview = action.comment[:100].replace('\n', ' ') + ('...' if len(action.comment) > 100 else '')
                print(f"    Comment: \"{comment_preview}\"")
        
        print("\n" + "="*80)
    
    def interactive_approve(self) -> None:
        """
        Interactive approval prompt. User can approve/reject/edit each action.
        """
        if not self.pending_actions:
            print("[INFO] No pending actions to approve.")
            return
        
        while self.pending_actions:
            self.display_pending()
            
            try:
                user_input = input("\n[ACTION] Enter action (a=approve, r=reject, q=quit, or index number): ").strip().lower()
                
                if user_input == 'q':
                    print("[INFO] Quitting approval process. Pending actions remain.")
                    break
                
                if user_input == 'a':
                    # Approve all
                    for action in self.pending_actions[:]:
                        self.approve_action(0)
                    print(f"[OK] Approved all {len(self.approved_actions)} actions.")
                    break
                
                if user_input == 'r':
                    # Reject all
                    count = len(self.pending_actions)
                    for _ in range(count):
                        self.reject_action(0, "Rejected by user")
                    print(f"[OK] Rejected all {count} actions.")
                    break
                
                # Try to parse as index
                try:
                    index = int(user_input)
                    if 0 <= index < len(self.pending_actions):
                        action = self.pending_actions[index]
                        choice = input(f"\nApprove issue #{action.issue_number}? (y/n): ").strip().lower()
                        if choice == 'y':
                            self.approve_action(index)
                        else:
                            self.reject_action(index, "Rejected by user")
                    else:
                        print(f"[ERROR] Invalid index. Choose 0-{len(self.pending_actions)-1}")
                except ValueError:
                    print("[ERROR] Invalid input. Try 'a' (approve all), 'r' (reject all), 'q' (quit), or an index number.")
            
            except KeyboardInterrupt:
                print("\n[INFO] Interrupted. Pending actions remain.")
                break
    
    def save_approvals(self, filename: str = "approvals.json") -> None:
        """
        Save approval/rejection log to a JSON file.
        
        Args:
            filename: Output filename
        """
        log = {
            "approved": [
                {
                    "issue_number": a.issue_number,
                    "issue_title": a.issue_title,
                    "action_type": a.action_type,
                    "labels": a.labels,
                    "comment": a.comment,
                    "approval_note": a.approval_note
                }
                for a in self.approved_actions
            ],
            "rejected": [
                {
                    "issue_number": a.issue_number,
                    "issue_title": a.issue_title,
                    "action_type": a.action_type,
                    "reason": a.approval_note
                }
                for a in self.rejected_actions
            ]
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(log, f, indent=2)
            print(f"[OK] Approval log saved to {filename}")
        except Exception as e:
            print(f"[ERROR] Error saving approvals: {e}")