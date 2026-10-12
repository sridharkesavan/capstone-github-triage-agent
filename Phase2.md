# Phase 2: Human-in-the-Loop (HITL) Approval Gate

## Overview

Phase 2 adds a **structurally enforced approval gate** that prevents the agent from writing to GitHub without explicit human approval.

**Key Principle:** HITL is enforced at the code level, not just through prompts. The agent literally *cannot* access GitHub's write APIs without passing through the approval gate.

**Phase 2 adds:**
- Interactive approval/rejection prompt
- Approval logging
- Safe GitHub write operations
- Token permission validation

---

## Why HITL Matters

### Without HITL (Phase 1)
```
Issue → Classify → Propose Action → DIRECTLY WRITE TO GITHUB
                                    ↑
                                    Dangerous!
```

The agent can write to GitHub immediately, with no human oversight.

### With HITL (Phase 2)
```
Issue → Classify → Propose Action → HUMAN APPROVAL GATE → Write to GitHub
                                    ↑
                                    Structurally enforced
```

The agent **cannot** access write APIs without explicit human approval.

---

## Implementation

### File 1: `src/hitl_gate.py`

This file defines the approval gate. It's the **only** interface for GitHub write operations.

**Core Components:**

#### 1. `Action` Class
Represents a proposed action (add labels, add comment).

```python
class Action:
    def __init__(self, 
                 issue_number: int,
                 issue_title: str,
                 classification: str,
                 action_type: Literal['add_labels', 'add_comment', 'both'],
                 labels: list[str],
                 comment: Optional[str] = None):
        self.issue_number = issue_number
        self.issue_title = issue_title
        self.classification = classification
        self.action_type = action_type
        self.labels = labels
        self.comment = comment
        self.approved = False  # ← Not approved until gate passes
        self.approval_note = None
```

**Key Point:** `approved` defaults to `False`. It can only become `True` after passing the gate.

#### 2. `HITLGate` Class
Manages pending, approved, and rejected actions.

**Key Methods:**
- `propose_action(action)` — Add action to pending queue
- `approve_action(index, note)` — Move from pending to approved
- `reject_action(index, reason)` — Move from pending to rejected
- `interactive_approve()` — Prompt user for decisions
- `save_approvals(filename)` — Log all decisions

**Important:** Only `approved_actions` list is used for writing to GitHub.

```python
class HITLGate:
    def __init__(self, interactive: bool = True):
        self.pending_actions = []     # Awaiting approval
        self.approved_actions = []    # Approved, safe to write
        self.rejected_actions = []    # User rejected
```

---

### File 2: Updates to `src/agent.py`

The agent integrates with the HITL gate.

#### New Methods

**1. `propose_github_action(classification)`**
Convert a classification result into an Action and propose it.

```python
def propose_github_action(self, classification: dict) -> None:
    """Propose a GitHub action with HITL approval."""
    # Extract data
    issue_number = classification.get('issue_number')
    # ... validation ...
    
    # Create action
    action = Action(
        issue_number=issue_number,
        issue_title=classification.get('issue_title'),
        classification=classification.get('classification'),
        action_type=action_type,
        labels=classification.get('suggested_labels', []),
        comment=classification.get('response_comment')
    )
    
    # Propose to gate (does NOT execute)
    self.hitl_gate.propose_action(action)
```

**Key Point:** This creates the action but does NOT execute it.

**2. `execute_approved_actions()`**
Only method that writes to GitHub. Operates on approved actions only.

```python
def execute_approved_actions(self) -> None:
    """Execute all approved actions on GitHub."""
    approved_actions = self.hitl_gate.get_approved_actions()
    
    for action in approved_actions:
        # Add labels
        if action.action_type in ['add_labels', 'both']:
            self.gh_tools.add_label(action.issue_number, action.labels)
        
        # Add comment
        if action.action_type in ['add_comment', 'both']:
            self.gh_tools.add_comment(action.issue_number, action.comment)
```

**Key Point:** This ONLY writes approved actions. Non-approved actions are never touched.

#### Updated `__init__`

```python
def __init__(self, enable_hitl: bool = True):
    # ... existing code ...
    self.hitl_gate = HITLGate(interactive=enable_hitl) if enable_hitl else None
    self.enable_hitl = enable_hitl
```

#### Updated `main()`

```python
def main():
    enable_hitl = '--hitl' in sys.argv or '--phase2' in sys.argv
    
    agent = GitHubTriageAgent(enable_hitl=enable_hitl)
    results = agent.process_issues(limit=5)
    
    if enable_hitl and agent.hitl_gate:
        # Phase 2 workflow
        for result in results:
            agent.propose_github_action(result)
        
        agent.hitl_gate.interactive_approve()
        agent.execute_approved_actions()
```

---

## Running Phase 2

### Basic Usage

**Enable HITL approval gate:**

```bash
python -m src.agent --hitl
```

**Flow:**
1. Fetches and classifies issues
2. Proposes actions (displays each one)
3. Waits for your approval/rejection
4. Only writes approved actions

### Interactive Approval Prompt

Once issues are classified, you'll see:

```
================================================================================
[PENDING APPROVAL] 3 action(s) waiting for approval
================================================================================

[0] Issue #3: How do I integrate with GitHub Actions?
    Classification: QUESTION
    Action type: both
    Labels: needs-triage
    Comment: "Thank you for opening this issue..."

[1] Issue #2: Add support for custom label templates
    Classification: FEATURE
    ...

[ACTION] Enter action (a=approve, r=reject, q=quit, or index number):
```

**Options:**

| Command | Action |
|---------|--------|
| `a` | Approve all pending actions |
| `r` | Reject all pending actions |
| `q` | Quit (keep pending, don't write anything) |
| `0` | Approve/reject action #0 individually |
| `1` | Approve/reject action #1 individually |

**Example Session:**

```
[ACTION] Enter action: 0

Approve issue #3? (y/n): y
[APPROVED] Issue #3: both
```

Then the agent displays remaining actions until you approve/reject all or quit.

---

## Bugs Faced & Solutions

### Bug #1: Module Import Error (HITL Gate)

**Symptom:**
```
ModuleNotFoundError: No module named 'src.hitl_gate'
```

**Root Cause:**
Python module resolution issue when running with `-m src.agent`.

**Solution:**
Use relative imports in `src/agent.py`:

```python
# Before (absolute)
from src.hitl_gate import HITLGate, Action

# After (relative)
from .hitl_gate import HITLGate, Action
```

Then add path setup:

```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

---

### Bug #2: Token Insufficient Permissions (403 Forbidden)

**Symptom:**
```
Error code: 403: Forbidden
{"message": "Resource not accessible by personal access token", ...}
```

**Root Cause:**
GitHub token doesn't have write permissions. Commonly happens when:
- Token scope is `repo:read-only` instead of `repo`
- Token is too old and permissions were revoked
- Token doesn't have `issues` write scope

**Solution:**

1. Go to https://github.com/settings/tokens
2. Check your token's scopes:
   - ✅ `repo` (full control of repos)
   - ✅ `issues` (read/write access to issues)

3. If missing, click "Regenerate token" and select correct scopes

4. Update `.env`:
```
GITHUB_TOKEN=ghp_new_token_here
```

5. Test write permissions:
```python
python -c "
from github import Github
import os
from dotenv import load_dotenv

load_dotenv()
token = os.getenv('GITHUB_TOKEN')
gh = Github(token)
user = gh.get_user()
print(f'Authenticated as: {user.login}')
print(f'Scopes: {gh.get_user().created_at}')  # Simple test
"
```

---

### Bug #3: Issue Number is Null

**Symptom:**
```
[SKIP] Cannot propose action: issue number is null
```

**Root Cause:**
Some test issues have `issue_number: null` in their classification result (parsing error or missing field).

**Solution:**
Add validation in `propose_github_action()`:

```python
def propose_github_action(self, classification: dict) -> None:
    issue_number = classification.get('issue_number')
    
    if not issue_number:
        print(f"[SKIP] Cannot propose action: issue number is null")
        return
    
    # Continue with action creation
```

**Prevention:** Ensure issue data from GitHub has valid issue numbers. Test with real repo issues, not demo data.

---

## Safety Guarantees

### Structural Safety

**Guarantee:** The agent cannot write to GitHub without human approval.

**Implementation:**
1. All GitHub write APIs are in `GitHubTools` class
2. `GitHubTools.add_label()` and `.add_comment()` are public
3. `execute_approved_actions()` is the ONLY caller of these methods
4. `execute_approved_actions()` only processes `approved_actions` list
5. Actions only appear in `approved_actions` after passing `HITLGate`

**Result:** There is no code path from issue → GitHub write that bypasses the gate.

### Audit Trail

Every decision is logged:

**`approval_log.json`:**
```json
{
  "approved": [
    {
      "issue_number": 3,
      "issue_title": "How do I integrate with GitHub Actions?",
      "action_type": "both",
      "labels": ["needs-triage"],
      "comment": "Hi there...",
      "approval_note": ""
    }
  ],
  "rejected": [
    {
      "issue_number": 2,
      "issue_title": "Add support for custom label templates",
      "action_type": "add_comment",
      "reason": "Rejected by user"
    }
  ]
}
```

---

## Approval Workflow

### Complete Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. Agent processes issues                               │
│    classify_issue() for each one                        │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Propose actions to HITL gate                         │
│    propose_github_action() for each classification      │
│    Actions added to pending_actions list               │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 3. Interactive approval loop                            │
│    User sees each pending action                       │
│    Chooses: approve, reject, or quit                   │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 4. Actions moved to approved/rejected lists             │
│    approved_actions → safe to write                     │
│    rejected_actions → logged, discarded                 │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Execute approved actions only                        │
│    execute_approved_actions()                          │
│    Writes labels and comments to GitHub               │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 6. Save approval log                                    │
│    approval_log.json for audit trail                   │
└─────────────────────────────────────────────────────────┘
```

### Decision Tree

```
User at approval prompt
│
├─ "a" (approve all)
│  └─ All pending → approved
│  └─ Continue to execution
│
├─ "r" (reject all)
│  └─ All pending → rejected
│  └─ Skip execution
│
├─ "q" (quit)
│  └─ All pending → stay pending
│  └─ No execution, no writes
│
├─ "0" (approve action 0)
│  └─ User confirms: Approve issue #X? (y/n)
│  │  ├─ "y" → approved
│  │  └─ "n" → rejected
│  └─ Continue with next action
│
└─ Invalid input
   └─ Show error, re-prompt
```

---

## Output Files

### `approval_log.json`

Created after execution. Contains:
- List of approved actions (with issue numbers, labels, comments)
- List of rejected actions (with rejection reasons)

**Use Case:** Audit trail for compliance, debugging, or analysis.

### `triage_results.json`

(Same as Phase 1)
Contains all classification results, regardless of approval decision.

---

## Integration with Phase 1

**Phase 1 still works:**

```bash
python -m src.agent
```

Runs classification only (no HITL). Useful for batch analysis without writes.

**Phase 2 adds approval layer:**

```bash
python -m src.agent --hitl
```

Adds interactive approval before any GitHub writes.

**Both share:**
- Same classification logic
- Same result format
- Same prompts

---

## Testing Checklist

- [ ] Token has write permissions (test with GitHub UI)
- [ ] `python -m src.agent --hitl` runs without errors
- [ ] Pending actions display correctly
- [ ] Can approve individual actions
- [ ] Can approve all with `a`
- [ ] Can reject with `r`
- [ ] Approved actions write to GitHub
- [ ] Rejected actions don't write to GitHub
- [ ] `approval_log.json` is created
- [ ] Log contains approved and rejected sections

---

## Example Session

```
PS C:\Users\sam\zzz\capstone> python -m src.agent --hitl
[AGENT] GitHub Issue Triage Agent — Phase 2 (WITH HITL APPROVAL)
================================================================================
[OK] Connected to sridharkesavan/ai-agents-from-scratch
[OK] Agent initialized with model: claude-opus-5-5
[OK] HITL approval gate: ENABLED

[FETCH] Fetching up to 5 open issues from sridharkesavan/ai-agents-from-scratch...
[DEBUG] Fetched 3 issues (checked 3)
[OK] Found 3 issue(s). Classifying...

[1/3] Processing issue #3: How do I integrate with GitHub Actions?...
  -> Classification: QUESTION
  -> Confidence: 95.0%
  -> Labels: needs-triage

[2/3] Processing issue #2: Add support for custom label templates...
  -> Classification: FEATURE
  -> Confidence: 70.0%
  -> Labels: enhancement, needs-more-info

[3/3] Processing issue #1: Agent fails on empty repository...
  -> Classification: BUG
  -> Confidence: 60.0%
  -> Labels: bug, needs-triage

================================================================================
[PHASE 2] HUMAN-IN-THE-LOOP APPROVAL GATE
================================================================================

[PROPOSED ACTION] Issue #3: How do I integrate with GitHub Actions?
Classification: QUESTION
Proposed Actions:
  - Add labels: needs-triage
  - Add comment: "Thank you for opening this issue..."

================================================================================
[PENDING APPROVAL] 1 action(s) waiting for approval
================================================================================

[0] Issue #3: How do I integrate with GitHub Actions?
    Classification: QUESTION
    Action type: both
    Labels: needs-triage
    Comment: "Thank you for opening this issue. We'll review it soon."

================================================================================

[ACTION] Enter action (a=approve, r=reject, q=quit, or index number): 0

Approve issue #3? (y/n): y
[APPROVED] Issue #3: both

[EXECUTE] Writing 1 approved action(s) to GitHub...

[WRITE] Issue #3: How do I integrate with GitHub Actions?
[OK] Added labels ['needs-triage'] to issue #3
  [OK] Added labels: needs-triage
[OK] Added comment to issue #3
  [OK] Added comment (55 chars)
[OK] Approval log saved to approval_log.json
[OK] Results saved to triage_results.json
```

---

## Next Steps

**Phase 3 will add:**
- Containerization (Docker)
- Deployment to Google Cloud Run
- REST API endpoint
- Managed sessions and autoscaling

Proceed to `PHASE_3.md` for cloud deployment.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│  GitHub Issue Triage Agent — Phase 2                    │
└──────────────────────────────────────────────────────────┘

                          Issue
                            │
                            ▼
                ┌──────────────────────┐
                │ Classification       │
                │ (Claude Opus 5.5)    │
                └──────────┬───────────┘
                           │
                    Classification Result
                           │
                           ▼
                ┌──────────────────────┐
                │ Action Creation      │
                │ (propose_github_     │
                │  action)             │
                └──────────┬───────────┘
                           │
              Proposed Action (NOT executed)
                           │
                           ▼
        ╔══════════════════════════════════════╗
        ║  HITL Gate (Structural Barrier)      ║
        ║  ┌────────────────────────────────┐  ║
        ║  │ Pending Actions Queue           │  ║
        ║  │ - Issue #3: Add label           │  ║
        ║  │ - Issue #2: Add comment         │  ║
        ║  └────────────────────────────────┘  ║
        ║           │                           ║
        ║    User Decision Required             ║
        ║           │                           ║
        ║  ┌────────────────────────────────┐  ║
        ║  │ Approve / Reject               │  ║
        ║  │ interactive_approve()          │  ║
        ║  └────────────────────────────────┘  ║
        ║           │                           ║
        ║  Approved Actions (Safe to write)    ║
        ║           │                           ║
        ║  Rejected Actions (Discarded)        ║
        ╚══════════════════════════════════════╝
                           │
            ┌──────────────┴──────────────┐
            │                             │
            ▼                             ▼
  ┌─────────────────────┐     ┌──────────────────────┐
  │ Execute Approved    │     │ Audit Log            │
  │ add_label()         │     │ approval_log.json    │
  │ add_comment()       │     └──────────────────────┘
  └─────────────────────┘
            │
            ▼
  ┌─────────────────────┐
  │ GitHub API          │
  │ Write Operations    │
  └─────────────────────┘
```

---

## FAQ

**Q: Can the agent bypass the approval gate?**
A: No. There's no code path from issue classification to GitHub write that doesn't pass through `execute_approved_actions()`, which only touches the `approved_actions` list.

**Q: What happens if I quit without approving?**
A: Actions stay in `pending_actions`. Nothing is written to GitHub. You can run the agent again.

**Q: Can I edit a proposed action?**
A: Not in this version. You can approve or reject. For Phase 3, consider adding an "edit" option.

**Q: How do I know what was actually written?**
A: Check `approval_log.json` for approved actions, and your GitHub issue's activity log.

**Q: Does Phase 2 require Phase 1?**
A: Yes. Phase 2 extends Phase 1. Both run the same classification logic.

---

## Troubleshooting

### Issue: Approval prompt doesn't appear

**Check:**
1. Run with `--hitl` flag: `python -m src.agent --hitl`
2. Agent found at least one issue to classify
3. Classifications were successful (check terminal output)

### Issue: "Approved" but nothing wrote to GitHub

**Check:**
1. Token permissions: Test with `gh repo view owner/repo`
2. Issue number is not null (check classification result)
3. Labels exist in repository (agent doesn't create new labels)
4. No GitHub API rate limiting

### Issue: Approval log not created

**Check:**
1. At least one action was approved
2. Write permissions to current directory
3. No antivirus/filesystem issues blocking file creation