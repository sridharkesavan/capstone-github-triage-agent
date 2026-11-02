# Phase 3: REST API and Cloud Run Deployment

**Status:** deployed to Cloud Run (private) and verified end to end.
**Last updated:** 2026-11-02

This file replaces the first version of the Phase 3 notes. That version described the first deployment attempt (public service, position-based approvals, up to 10 instances). Several of those choices were wrong, and this file records what is actually deployed and why.

---

## 1. What Phase 3 adds

Phase 2 was a command-line tool with a human approval gate. Phase 3 wraps the same agent in a Flask REST API, packages it with Docker, and runs it on Google Cloud Run.

```
GitHub issues
     |
     v
POST /triage      -> fetch open issues, classify with Claude, propose actions
     |
     v
GET /approvals    -> a human reads each proposed label and comment
     |
     v
POST /approve  or  POST /reject      (by action id)
     |
     v
POST /execute     -> writes ONLY approved actions to GitHub
```

The safety rule is the same as in Phase 2: **nothing is written to GitHub unless a human approved that exact action.** What changed is how actions are identified (see section 5).

---

## 2. Files

| File | Purpose |
|---|---|
| `main.py` | Flask API: all endpoints below |
| `src/agent.py` | Fetches issues, classifies with Claude, proposes actions |
| `src/tools.py` | PyGithub wrapper (the only place that writes to GitHub) |
| `src/hitl_gate.py` | The approval gate: `Action`, `HITLGate` |
| `config/prompts.py` | System prompt and output format for classification |
| `Dockerfile`, `.dockerignore` | Container build (used by Cloud Run) |
| `tests/test_gate_invariant.py` | 5 tests for the approval invariant |
| `requirements.txt` | Dependencies (needs `anthropic>=0.50.0`, see section 8) |

**Superseded, do not use:** `app.yaml` (an App Engine format that Cloud Run ignores) and `deploy.sh` (written for the first attempt: public service, up to 10 instances, bash only). The deploy command in section 6 replaces both.

---

## 3. API reference

All request and response bodies are JSON.

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/` | | Endpoint list |
| GET | `/health` | | `agent_initialized` should be `true` |
| GET | `/status` | | Counts: pending, approved, rejected, executed |
| POST | `/triage` | `{"repo": "owner/name", "limit": 5}` | Classify open issues and create proposals. `repo` is optional and defaults to the `GITHUB_REPO` env var |
| GET | `/approvals` | | List pending proposals |
| POST | `/approve` | `{"action_id": "6369888f", "note": "..."}` | Approve one proposal |
| POST | `/reject` | `{"action_id": "ac8ea992", "reason": "..."}` | Reject one proposal |
| POST | `/execute` | | Write all approved actions to GitHub, once |

An **action id** is an 8-character value generated per proposal (for example `6369888f`). It is returned by `/triage` and `/approvals`. Ids are not positions, and they change on every `/triage` run, so always copy them from the latest response.

---

## 4. Two repos, two roles

- **The code repo** (`capstone-github-triage-agent`) is where this project lives.
- **`GITHUB_REPO`** is the repo whose **issues the agent triages**. For testing this is `sridharkesavan/ai-agents-from-scratch`, which holds the test issues.

They are different repos on purpose. Pointing `GITHUB_REPO` at the code repo works, but it has no issues to triage.

---

## 5. The bug found in the cloud, and the fix

### What happened

On Cloud Run, the test was: approve issue #4, reject issue #3, then execute.

| Step | API response |
|---|---|
| approve | issue 4 approved |
| reject | issue 3 rejected |
| execute | **wrote to issue 3** |

The rejected issue was written to. GitHub confirmed it: #4 had no label, and #3 had extra comments.

### Root causes (three, in `main.py` and `hitl_gate.py`)

1. **Position-based approvals.** `/approve` and `/reject` passed a list index to the gate, and the gate did `pending_actions.pop(index)`. After every pop, every later position shifts, so an index could point at a different issue than the API reported.
2. **Stale proposals.** `/triage` cleared the API's dictionary but never the gate's list, so proposals from earlier runs stayed at the front.
3. **Approvals never expired.** `/execute` read a copy of the approved list and never emptied it, so the same approval would execute again on every call.

The API response read from a dictionary while the write came from the gate's lists. The two disagreed, and nothing checked them against each other.

### Fix

- Every `Action` gets a unique id (`uuid`) at creation.
- The gate gained id-based methods: `approve_by_id`, `reject_by_id`, `clear_pending`, `pop_approved`. The old index-based methods remain only for the CLI.
- `/triage` clears the gate's pending list and uses each action's own id as the API key.
- `/execute` calls `pop_approved()`, which returns the approved actions **and empties the list**, then re-checks `approved is True` for each one.
- `/execute` saves the audit log before popping, and removes only the executed proposals from the API's dictionary instead of clearing everything.

### The invariant, as tests

`tests/test_gate_invariant.py` encodes the rule "the issues written to are exactly the issues approved, and nothing else":

1. only approved actions are executed (the exact cloud bug)
2. approval survives position shifts
3. an approved action executes only once
4. an unknown id is never approved
5. clearing pending drops old runs

Run them with `python3 -m pytest tests -q`. Expect `5 passed`.

### Lesson

The classification looked correct and the API responses looked correct. The failure was only visible by checking what actually landed on GitHub. A passing response is not a correct system. The gate had to be tested on its own invariant, not just on the happy path.

---

## 6. Deploying to Cloud Run

### Why the service is private and limited to one instance

- **`--no-allow-unauthenticated`:** the service can write to GitHub and spend Anthropic credits, and `/approve` and `/execute` are the approval gate itself. A public URL would let anyone approve their own actions.
- **`--max-instances 1` and one gunicorn worker:** pending approvals live in memory. A second instance or worker has its own memory and would not see proposals made on the first. (See limitations.)

### Dockerfile

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 --timeout 300 main:app
```

`.dockerignore` must exclude `.env`, `.git`, `__pycache__/`, `venv/`, and the two output JSON files, so secrets never enter the image.

### One-time setup (macOS or Linux)

```bash
PROJECT_ID=github-triage-agent-513401
gcloud config set project $PROJECT_ID
gcloud billing projects describe $PROJECT_ID        # needs billingEnabled: true
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
```

### Secrets (read from .env, never typed or pasted)

```bash
grep '^ANTHROPIC_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d "\r\n\"'" \
  | gcloud secrets create anthropic-api-key --data-file=-
grep '^GITHUB_TOKEN=' .env | head -1 | cut -d= -f2- | tr -d "\r\n\"'" \
  | gcloud secrets create github-token --data-file=-

PROJECT_NUM=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUM}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Verify the lengths without printing the keys:

```bash
gcloud secrets versions access latest --secret=anthropic-api-key | wc -c   # about 100 or more
gcloud secrets versions access latest --secret=github-token | wc -c        # about 40 or more
```

To replace a secret, use `gcloud secrets versions add` (same pipe) and then roll a new revision, because Cloud Run reads secrets when an instance starts.

### First deploy

```bash
gcloud run deploy github-triage-agent \
  --source . \
  --region us-central1 \
  --no-allow-unauthenticated \
  --max-instances 1 \
  --memory 512Mi \
  --timeout 300 \
  --set-env-vars GITHUB_REPO=sridharkesavan/ai-agents-from-scratch \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest,GITHUB_TOKEN=github-token:latest
```

### Redeploy after code changes

Existing env vars and secrets carry over:

```bash
gcloud run deploy github-triage-agent --source . --region us-central1 \
  --no-allow-unauthenticated --max-instances 1
```

### Windows notes

Use **cmd**, not PowerShell, for gcloud (it was not on the PowerShell PATH). Line continuation is `^`, not `\`. `bash deploy.sh` does not work without WSL. Create secrets with `echo|set /p="KEY" | gcloud secrets create ...` to avoid a trailing newline.

---

## 7. Testing

### Locally in Docker (reads GitHub, writes only if you call `/execute`)

```bash
docker build -t github-triage-agent .
docker run --rm -p 8080:8080 --env-file .env github-triage-agent
curl http://localhost:8080/health
```

### Against the private cloud service

The service needs credentials, so use gcloud's authenticated local proxy:

```bash
gcloud run services proxy github-triage-agent --region us-central1 --port 9090
```

Then use `http://localhost:9090` for everything below.

### Full approval test

```bash
# 1. Classify and list proposals (note the ids)
curl -s -X POST http://localhost:9090/triage -H "Content-Type: application/json" \
  -d '{"repo": "sridharkesavan/ai-agents-from-scratch", "limit": 10}'

# 2. Read each proposal BEFORE approving
curl -s http://localhost:9090/approvals

# 3. Approve one, reject another (use ids from step 1)
curl -X POST http://localhost:9090/approve -H "Content-Type: application/json" \
  -d '{"action_id": "ID_A", "note": "test"}'
curl -X POST http://localhost:9090/reject -H "Content-Type: application/json" \
  -d '{"action_id": "ID_B", "reason": "already triaged"}'

# 4. Check state, then execute
curl http://localhost:9090/status
curl -X POST http://localhost:9090/execute

# 5. A second execute must do nothing
curl -X POST http://localhost:9090/execute     # expect "status":"no_actions"
```

Then **check GitHub**. The approved issue should have the label (and a comment if the proposal had one). The rejected issue and every undecided issue must be unchanged.

### Logs

```bash
gcloud run services logs read github-triage-agent --region us-central1 --limit 50
```

---

## 8. Problems hit during Phase 3

| Problem | Cause | Fix |
|---|---|---|
| `Billing must be enabled` | New GCP project had no billing account | Link a billing account to the project, confirm with `gcloud billing projects describe` |
| Project not visible | Free trial started under a different Google account | Create a new project under the right account, update every project id and project number |
| `bash` fails on Windows | No WSL distribution installed | Run gcloud directly, no script |
| `gcloud` not recognized in PowerShell | Not on that shell's PATH | Use cmd |
| `unrecognized arguments: --runtime` | Not a `gcloud run deploy` flag | Remove it, Cloud Run detects the runtime |
| `Client.__init__() got an unexpected keyword argument 'proxies'` | Pinned old `anthropic` with a newer `httpx` in a clean build | `anthropic>=0.50.0` in `requirements.txt`. Worked locally only because an upgraded copy was installed |
| `ANTHROPIC_API_KEY not set` on Cloud Run | Secrets were never created. A multi-line paste into `read -s` swallowed the key | Create secrets from `.env` with the commands in section 6 |
| No issues to triage | `GITHUB_REPO` pointed at the code repo | Set it to the repo whose issues should be triaged |
| Approve and execute disagreed | Position-based approvals (section 5) | Id-based gate plus tests |

---

## 9. Known limitations

- **State is in memory.** Pending approvals disappear when the instance restarts or scales to zero after idling. A persistent store (Firestore or similar) is the proper fix.
- **One instance only.** That is a consequence of in-memory state, not a goal.
- **`approval_log.json` is overwritten** on each execute. An append-only log would be a better audit trail.
- **Some proposals have no comment.** The model sometimes returns no `response_comment` (seen on issues with empty bodies). `/execute` correctly skips empty comments, but this should be measured in Phase 4.
- **Access control is Cloud Run IAM only.** Anyone with the right Google identity can approve. Fine for one user, not for a team.
