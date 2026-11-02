# GitHub Issue Triage Agent

An AI agent that reads open GitHub issues, classifies them (bug, feature, question, duplicate), and proposes labels and a reply comment. **It never writes to GitHub until a human approves the specific action.** Runs locally, in Docker, or on Google Cloud Run.

Built as the capstone of a self-taught 6-week AI agents course.

## How it works

```
GitHub issues -> classify with Claude -> propose actions -> HUMAN APPROVES -> write to GitHub
                                                              |
                                                          reject = discarded
```

The approval gate is enforced in code, not in the prompt. Each proposed action has a unique id. Only actions that were approved by id can reach the GitHub write calls, and each approval executes once.

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Local classifier (read-only) | Done |
| 2 | Human-in-the-loop approval gate (CLI) | Done |
| 3 | REST API, Docker, Cloud Run (private) | Done, verified end to end |
| 4 | Evals and guardrails | Next |
| 5 | Enterprise deployment simulation | Optional, later |

Details for each phase: `Phase1.md`, `Phase2.md`, `Phase3.md`. Working notes: `NOTES.md`.

## Quick start

Requires Python 3.12+, Docker, and API keys.

```bash
git clone https://github.com/sridharkesavan/capstone-github-triage-agent.git
cd capstone-github-triage-agent
```

Create a `.env` file (never commit it):

```
ANTHROPIC_API_KEY=your-key
GITHUB_TOKEN=your-token          # needs repo and issues write scope
GITHUB_REPO=owner/repo-to-triage # the repo whose issues get triaged
```

Run in Docker and check health:

```bash
docker build -t github-triage-agent .
docker run --rm -p 8080:8080 --env-file .env github-triage-agent
curl http://localhost:8080/health      # expect "agent_initialized": true
```

Or run the CLI with the approval prompt:

```bash
python -m src.agent --hitl
```

Run the tests:

```bash
python3 -m pytest tests -q             # expect 5 passed
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Pending, approved, rejected, executed counts |
| POST | `/triage` | Classify open issues and create proposals |
| GET | `/approvals` | List pending proposals |
| POST | `/approve` | Approve one proposal by `action_id` |
| POST | `/reject` | Reject one proposal by `action_id` |
| POST | `/execute` | Write approved actions to GitHub, once |

Request and response details, deployment steps, and the bug story are in `Phase3.md`.

## Project layout

```
src/agent.py            classification and orchestration
src/tools.py            GitHub API wrapper (the only code that writes)
src/hitl_gate.py        approval gate
config/prompts.py       system prompt and output format
main.py                 Flask API
Dockerfile              container for Cloud Run
tests/                  approval-gate invariant tests
Phase1.md .. Phase3.md  per-phase documentation
```

`app.yaml` and `deploy.sh` are from the first deployment attempt and are superseded by the commands in `Phase3.md`.

## Deploying

The Cloud Run service is private and runs a single instance, because pending approvals are held in memory. The full command, secret setup, and the reasons behind each flag are in `Phase3.md` section 6.

## Key lessons so far

- Check `stop_reason` and parse model output defensively.
- Deterministic guardrails sit on top of model behavior, not instead of it.
- A passing response and a correct system are different things: the approval gate looked right in every API response and still wrote to the wrong issue. Verify what actually lands on GitHub.
- A fix that works on your machine is not a fix until it works from a clean build.

## Author

Sridhar Kesavan (Kevin), Engineering Manager, Tokyo.
