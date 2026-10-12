# Phase 1: Local ADK Agent for GitHub Issue Triage

## Overview

Phase 1 builds a **local, read-only GitHub issue triage agent** that:
- Fetches open issues from a GitHub repository
- Classifies them into categories (bug/feature/question/duplicate)
- Suggests appropriate labels
- Drafts professional response comments
- **Does NOT write to GitHub** (that's Phase 2)

This phase demonstrates the core agent logic using the Anthropic API and PyGithub without any approval gates or cloud deployment.

---

## Prerequisites

### System Requirements
- **Python 3.12+** (tested with 3.13.1)
- **Pip** (Python package manager)
- **Git** (optional, for version control)
- **Windows/Mac/Linux** (platform-agnostic)

### API Keys & Credentials
1. **Anthropic API Key**
   - Get from: https://console.anthropic.com/account/keys
   - Required scope: Access to Claude models

2. **GitHub Personal Access Token**
   - Get from: https://github.com/settings/tokens
   - Required scopes: `repo` (read access to public/private repos)
   - Note: For Phase 1, read-only is fine

3. **GitHub Repository**
   - Must have at least one open issue for testing
   - Public or private (token must have access)

---

## Setup Instructions

### Step 1: Create Project Directory

```bash
mkdir capstone
cd capstone
```

### Step 2: Create Folder Structure

Create the following folder structure:

```
capstone/
├── src/
│   ├── __init__.py
│   ├── agent.py
│   └── tools.py
├── config/
│   └── prompts.py
├── tests/
├── .env                  (create manually)
├── .gitignore           (create manually)
├── requirements.txt     (create manually)
├── README.md
└── NOTES.md
```

**PowerShell command:**
```powershell
mkdir src, tests, config
New-Item -Path src -Name __init__.py -ItemType File
New-Item -Path .env -ItemType File
New-Item -Path .gitignore -ItemType File
New-Item -Path requirements.txt -ItemType File
```

### Step 3: Create `.env` File

Edit `.env` and add:

```
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxx

# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxx
GITHUB_REPO=username/repo-name

# Optional: Langfuse (for observability)
LANGFUSE_PUBLIC_KEY=your-key
LANGFUSE_SECRET_KEY=your-key
LANGFUSE_HOST=https://cloud.langfuse.com
```

Replace values with your actual credentials.

### Step 4: Create `.gitignore`

```
.env
__pycache__/
*.pyc
.DS_Store
*.egg-info/
.venv
venv/
requirements-lock.txt
*.json
```

### Step 5: Create `requirements.txt`

```
anthropic==0.28.0
google-adk==0.1.0
PyGithub==2.1.1
python-dotenv==1.0.1
langfuse==3.0.0
```

### Step 6: Install Dependencies

```bash
pip install -r requirements.txt
```

Verify installation:

```bash
python -c "import anthropic; import github; print('✓ Setup successful')"
```

Expected output: `✓ Setup successful`

---

## Implementation

### File 1: `config/prompts.py`

This file defines the system prompts that guide Claude's classification logic.

**Purpose:**
- System prompt: Tells Claude how to classify issues
- Classification prompt: Template for analyzing individual issues
- Label mappings: Suggest labels based on classification
- Response templates: Generic fallback responses

**Key Points:**
- Classification rules are explicit (bug, feature, question, duplicate)
- Confidence scoring (0.0-1.0) helps gauge certainty
- JSON output format makes parsing predictable

**Code:**
```python
"""
System prompts and classification logic for GitHub issue triage agent.
"""

SYSTEM_PROMPT = """You are a GitHub issue triage expert. Your job is to analyze GitHub issues and classify them.

For each issue, you will:
1. Read the title and body
2. Classify it into ONE category: bug, feature, question, or duplicate
3. Suggest appropriate labels
4. Draft a professional response comment (if needed)

Classification rules:
- **bug**: Something is broken, not working as expected, or causing errors
- **feature**: A request for new functionality or enhancement
- **question**: User asking for help, clarification, or documentation
- **duplicate**: The issue has already been reported or addressed elsewhere

Output format (JSON):
{
  "issue_number": <int>,
  "issue_title": "<string>",
  "classification": "<bug|feature|question|duplicate>",
  "confidence": <0.0-1.0>,
  "suggested_labels": ["label1", "label2"],
  "response_comment": "<string or null>",
  "reasoning": "<brief explanation>"
}

Always be professional, helpful, and constructive. If unsure, pick the best fit and explain in reasoning.
"""

CLASSIFICATION_PROMPT = """
Analyze this GitHub issue and classify it:

Title: {title}
Body: {body}

Provide your classification in the JSON format specified in the system prompt.
"""

# Label mappings
LABEL_SUGGESTIONS = {
    "bug": ["bug", "needs-triage"],
    "feature": ["enhancement", "needs-triage"],
    "question": ["question", "documentation"],
    "duplicate": ["duplicate"],
}

# Response templates
RESPONSE_TEMPLATES = {
    "bug": "Thank you for reporting this issue. We've classified this as a bug. The team will investigate and get back to you soon.",
    "feature": "Thank you for the feature request. We've added this to our backlog for consideration.",
    "question": "Thank you for the question. This appears to be a support question. Please check our documentation or reach out on our support channels.",
    "duplicate": "Thank you for your report. This appears to be a duplicate of an existing issue. Please refer to the linked issue for updates.",
}
```

### File 2: `src/tools.py`

This file wraps the PyGithub library to interact with GitHub's REST API.

**Purpose:**
- Connect to GitHub repository
- Fetch open issues
- Prepare issue data for classification
- (Phase 2 will add label/comment writing here)

**Key Methods:**
- `get_open_issues()` — Fetch recent issues
- `get_issue()` — Fetch specific issue by number
- `add_label()` — Add labels (disabled in Phase 1)
- `add_comment()` — Add comments (disabled in Phase 1)

**Important:** The `get_open_issues()` method filters out pull requests. GitHub's API counts PRs in the `open_issues_count` but we want only actual issues.

**Code:**
```python
"""
GitHub API tools for the issue triage agent.
"""

import json
from typing import Optional
from github import Github
from github.GithubException import GithubException


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
            # Fetch issues explicitly (excludes PRs by default)
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
    
    def add_label(self, issue_number: int, labels: list[str]) -> bool:
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
    
    def add_comment(self, issue_number: int, comment: str) -> bool:
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
```

### File 3: `src/agent.py`

This is the main orchestration file. It ties together prompts, GitHub tools, and Claude API.

**Core Responsibilities:**
- Initialize Claude API client
- Fetch issues from GitHub
- Send issues to Claude for classification
- Parse Claude's JSON response
- Handle extended thinking blocks (Claude Opus 5.5 feature)
- Display and save results

**Key Methods:**
- `classify_issue()` — Send issue to Claude, parse response
- `process_issues()` — Batch process multiple issues
- `display_results()` — Format output for human reading
- `save_results()` — Write results to JSON file

**See full agent.py implementation in the codebase.**

---

## Running Phase 1

### Basic Usage (Demo Mode)

Test with sample issues (doesn't require real GitHub issues):

```bash
python -m src.agent --demo
```

**Output:**
- Classifies 3 demo issues
- Shows results in terminal
- Saves to `triage_results.json`

### Against Real Repository

Test against your actual GitHub repo:

```bash
python -m src.agent
```

**Requirements:**
- `.env` must have valid `GITHUB_TOKEN` and `GITHUB_REPO`
- Repository must have at least one open issue

**Output:**
- Fetches real issues
- Classifies each one
- Saves results to `triage_results.json`

---

## Bugs Faced & Solutions

### Bug #1: Unicode Encoding Error on Windows

**Symptom:**
```
UnicodeEncodeError: 'cp932' codec can't encode character '\U0001f680'
```

**Root Cause:**
Windows PowerShell uses `cp932` encoding by default, which doesn't support emoji characters.

**Solution:**
Remove all emoji from the code and replace with text labels:
- `🚀` → `[AGENT]`
- `✓` → `[OK]`
- `✗` → `[ERROR]`
- `📂` → `[FETCH]`

**Files Modified:**
- `src/agent.py`
- `src/tools.py`

**Example:**
```python
# Before
print("🚀 GitHub Issue Triage Agent")

# After
print("[AGENT] GitHub Issue Triage Agent")
```

---

### Bug #2: Model Not Found (404 Error)

**Symptom:**
```
Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', 'message': 'model: claude-opus-4'}}
```

**Root Cause:**
The model name `claude-opus-4` doesn't exist in your Anthropic account. Different API keys have access to different models.

**Solution:**
Query the available models and use one that actually exists:

```python
python -c "
import os
from dotenv import load_dotenv
import httpx

load_dotenv()
key = os.getenv('ANTHROPIC_API_KEY')
headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
response = httpx.get('https://api.anthropic.com/v1/models', headers=headers)
data = response.json()
for model in data.get('data', []):
    print(f'  - {model.get(\"id\")}')
"
```

**For this project:**
Use `claude-opus-5-5` (latest available model)

```python
self.model = "claude-opus-5-5"
```

---

### Bug #3: ThinkingBlock Error with Extended Thinking

**Symptom:**
```
'ThinkingBlock' object has no attribute 'text'
```

**Root Cause:**
Claude Opus 5.5 uses extended thinking — it returns both `ThinkingBlock` (internal reasoning) and `TextBlock` (the actual response). The code was only looking for `.text` on the first block.

**Solution:**
Iterate through all content blocks and extract the one with `.text`:

```python
# Before
response_text = response.content[0].text

# After
response_text = None
for block in response.content:
    if hasattr(block, 'text'):
        response_text = block.text
        break

if not response_text:
    raise ValueError("No text block found in response")
```

---

### Bug #4: JSON Parsing Error (Unterminated String)

**Symptom:**
```
Failed to parse JSON response: Unterminated string starting at: line 7 column 23
```

**Root Cause:**
Claude's response may include unescaped newlines in strings, or the JSON is wrapped in markdown code blocks (` ```json ... ``` `).

**Solution:**
Strip markdown code blocks before parsing:

```python
# Handle markdown code blocks
if "```json" in response_text:
    json_str = response_text.split("```json")[1].split("```")[0].strip()
elif "```" in response_text:
    json_str = response_text.split("```")[1].split("```")[0].strip()
else:
    json_str = response_text

classification = json.loads(json_str)
```

---

### Bug #5: Empty Issues List (Index Out of Range)

**Symptom:**
```
IndexError: list index out of range
```

**Root Cause:**
Tried to slice a paginated list directly (`issues[:limit]`), which failed when pagination hadn't loaded yet.

**Solution:**
Iterate manually with a counter instead of slicing:

```python
# Before
for issue in issues[:limit]:
    # process

# After
count = 0
for issue in issues:
    if count >= limit:
        break
    # process
    count += 1
```

---

### Bug #6: No Issues Found (All PRs)

**Symptom:**
```
[DEBUG] Fetched 0 issues (checked 28)
```

**Root Cause:**
GitHub's `open_issues_count` includes pull requests. The code was filtering them out, leaving nothing.

**Solution:**
Explicitly check `issue.pull_request` attribute:

```python
if issue.pull_request:
    continue  # Skip PRs

# Process actual issues only
```

---

## Output Files

### `triage_results.json`

Contains all classification results:

```json
[
  {
    "issue_number": 3,
    "issue_title": "How do I integrate with GitHub Actions?",
    "classification": "question",
    "confidence": 0.95,
    "suggested_labels": ["question", "ci/cd", "github-actions"],
    "response_comment": "Hi there, thanks for reaching out!...",
    "reasoning": "The user is asking how to..."
  }
]
```

---

## Testing Checklist

- [ ] Environment variables (.env) are set correctly
- [ ] GitHub token has `repo` read access
- [ ] Repository has at least 1 open issue
- [ ] `python -m src.agent --demo` works
- [ ] `python -m src.agent` fetches real issues
- [ ] Classifications are reasonable
- [ ] `triage_results.json` is created
- [ ] No GitHub writes occur (Phase 1 is read-only)

---

## Next Steps

**Phase 2 adds:**
- Human-in-the-loop approval gate
- Interactive CLI for approving/rejecting actions
- Safe GitHub write operations (only after approval)

Proceed to `PHASE_2.md` for the next steps.

---

## Troubleshooting

### Issue: "No open issues found"

**Check:**
1. Repository has open issues: Visit `https://github.com/owner/repo/issues`
2. Token has read access: Try `git clone` with the token
3. Repo name is correct in `.env`

### Issue: "API Key not found"

**Check:**
1. `.env` file exists in project root
2. `ANTHROPIC_API_KEY` line is not commented out
3. No extra spaces around the `=` sign

### Issue: Agent is slow

**Normal behavior:**
- First issue: ~5 seconds (API warmup)
- Subsequent issues: ~2-3 seconds each
- Extended thinking adds latency

**Speed up:**
- Reduce issue body length in `classify_issue()` (currently 500 chars)
- Use a faster model (trade-off: accuracy drops)

---

## Architecture Diagram

```
┌─────────────────┐
│  GitHub API     │
│  (PyGithub)     │
└────────┬────────┘
         │
         │ fetch issues
         ▼
┌─────────────────┐
│  GitHubTools    │
│  (src/tools.py) │
└────────┬────────┘
         │
         │ issue data
         ▼
┌──────────────────────────┐
│  GitHubTriageAgent       │
│  (src/agent.py)          │
│  - classify_issue()      │
│  - process_issues()      │
└────────┬─────────────────┘
         │
         │ issue + prompt
         ▼
┌──────────────────────┐
│  Anthropic Claude    │
│  API (claude-opus-5) │
└────────┬─────────────┘
         │
         │ JSON classification
         ▼
┌──────────────────────────┐
│  Results                 │
│ - Display to terminal    │
│ - Save to JSON file      │
└──────────────────────────┘
```

---

## Additional Resources

- [Anthropic API Docs](https://docs.anthropic.com)
- [PyGithub Docs](https://pygithub.readthedocs.io)
- [GitHub REST API Docs](https://docs.github.com/en/rest)
- [Python dotenv](https://github.com/theskumar/python-dotenv)