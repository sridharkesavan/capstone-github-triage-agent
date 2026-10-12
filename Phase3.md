# Phase 3: Cloud Run Deployment

## Overview

Phase 3 takes your local agent and deploys it as a **REST API on Google Cloud Run**.

**What changes:**

- **Phase 1 & 2:** CLI tool you run locally
  ```bash
  python -m src.agent --hitl
  ```

- **Phase 3:** Hosted web service
  ```bash
  curl https://your-agent.cloudfun.run/triage
  ```

**Benefits:**
- ✅ Always running (24/7)
- ✅ Accessible from anywhere
- ✅ Scalable (auto-scales with demand)
- ✅ Free tier available (up to 2M invocations/month)
- ✅ No local machine required

---

## Architecture

```
Your Local Code
      ↓
  Flask API
      ↓
Cloud Run (Python 3.12 runtime)
      ↓
Public REST Endpoint
```

**No Docker needed** — Cloud Run handles containerization automatically.

---

## Prerequisites

✅ Completed Phase 1 & 2
✅ `gcloud` CLI installed and authenticated
✅ Google Cloud project created (`github-triage-agent-511209`)
✅ `.env` file with API keys

---

## Files Needed for Phase 3

### New Files

1. **`main.py`** — Flask REST API server
2. **`app.yaml`** — Cloud Run configuration
3. **`deploy.sh`** — Deployment script
4. **`requirements.txt`** — Updated with Flask and gunicorn

### Existing Files (Unchanged)

- `src/agent.py`
- `src/tools.py`
- `src/hitl_gate.py`
- `config/prompts.py`
- `.env`

---

## Setup

### Step 1: Install Flask & Gunicorn Locally

```powershell
pip install Flask==3.0.0 gunicorn==21.2.0
```

### Step 2: Test Locally

Before deploying, test the Flask app locally:

```powershell
python main.py
```

Expected output:
```
[STARTUP] GitHub Issue Triage Agent — Phase 3
[INFO] Starting Flask development server...
[INFO] Visit http://localhost:8080 to see endpoints
 * Running on http://127.0.0.1:8080
```

Open another PowerShell and test:

```powershell
curl http://localhost:8080/
```

Should return:
```json
{
  "name": "GitHub Issue Triage Agent — Phase 3",
  "version": "3.0.0",
  "status": "running",
  "endpoints": { ... }
}
```

Stop the server with `Ctrl+C`.

---

## Deployment to Cloud Run

### Method 1: Using Deployment Script (Recommended)

On Mac/Linux:
```bash
chmod +x deploy.sh
./deploy.sh github-triage-agent
```

On Windows (PowerShell):
```powershell
bash deploy.sh github-triage-agent
```

Or manually using gcloud (below).

### Method 2: Manual Deployment

```powershell
gcloud run deploy github-triage-agent `
  --source . `
  --platform managed `
  --region us-central1 `
  --allow-unauthenticated `
  --set-env-vars="ANTHROPIC_API_KEY=$env:ANTHROPIC_API_KEY,GITHUB_TOKEN=$env:GITHUB_TOKEN,GITHUB_REPO=$env:GITHUB_REPO" `
  --memory 512Mi `
  --timeout 300 `
  --max-instances 10
```

### Deployment Steps

1. **Upload code** — gcloud uploads your local files
2. **Build** — Cloud Run builds the container (2-3 min)
3. **Deploy** — Service goes live (1 min)
4. **Assign URL** — Get a public endpoint like `https://github-triage-agent-xxxxx.run.app`

**Total time:** ~5 minutes

---

## REST API Endpoints

### 1. Health Check

```bash
GET /health
```

Check if the service is running.

**Response:**
```json
{
  "status": "healthy",
  "agent_initialized": true,
  "pending_approvals": 0,
  "executions": 0
}
```

### 2. Triage Issues

```bash
POST /triage
Content-Type: application/json

{
  "repo": "owner/repo",  (optional, uses .env default)
  "limit": 5
}
```

Classify issues in a repository.

**Response:**
```json
{
  "status": "success",
  "issues_found": 3,
  "pending_approvals": ["action_0", "action_1", "action_2"],
  "approvals": {
    "action_0": {
      "id": "action_0",
      "issue_number": 3,
      "issue_title": "How do I integrate with GitHub Actions?",
      "classification": "question",
      "labels": ["needs-triage"],
      "comment": "Thank you for opening..."
    }
  }
}
```

### 3. Get Pending Approvals

```bash
GET /approvals
```

List all pending approvals.

**Response:**
```json
{
  "pending": ["action_0", "action_1"],
  "count": 2,
  "approvals": { ... }
}
```

### 4. Approve Action

```bash
POST /approve
Content-Type: application/json

{
  "action_id": "action_0",
  "note": "Looks good"
}
```

Approve a proposed action.

**Response:**
```json
{
  "status": "approved",
  "action_id": "action_0",
  "issue_number": 3
}
```

### 5. Reject Action

```bash
POST /reject
Content-Type: application/json

{
  "action_id": "action_0",
  "reason": "Not appropriate"
}
```

Reject a proposed action.

**Response:**
```json
{
  "status": "rejected",
  "action_id": "action_0",
  "issue_number": 3,
  "reason": "Not appropriate"
}
```

### 6. Execute Approved Actions

```bash
POST /execute
```

Write all approved actions to GitHub.

**Response:**
```json
{
  "status": "executed",
  "approved_count": 1,
  "executed": [
    {
      "issue_number": 3,
      "actions": ["add_labels", "add_comment"]
    }
  ]
}
```

### 7. Get Status

```bash
GET /status
```

Get current agent status.

**Response:**
```json
{
  "status": "ready",
  "pending_approvals": 1,
  "approved_actions": 0,
  "rejected_actions": 1,
  "executions_completed": 1
}
```

---

## Testing the API

### Using curl

**Test health:**
```bash
curl https://your-service.run.app/health
```

**Trigger triage:**
```bash
curl -X POST https://your-service.run.app/triage \
  -H "Content-Type: application/json" \
  -d '{"limit": 3}'
```

**Approve action:**
```bash
curl -X POST https://your-service.run.app/approve \
  -H "Content-Type: application/json" \
  -d '{"action_id": "action_0", "note": "Approved"}'
```

**Execute:**
```bash
curl -X POST https://your-service.run.app/execute
```

### Using Postman

Import these as requests in Postman:

1. **GET** `https://your-service.run.app/health`
2. **POST** `https://your-service.run.app/triage`
   - Body: `{"limit": 5}`
3. **POST** `https://your-service.run.app/approve`
   - Body: `{"action_id": "action_0", "note": "Looks good"}`
4. **POST** `https://your-service.run.app/execute`

---

## Workflow Example

### Complete Approval Flow

```
1. Call /triage
   → Returns: pending_approvals: ["action_0", "action_1"]

2. Call /approvals
   → View details of each pending action

3. Call /approve with action_id: "action_0"
   → Approves issue #3

4. Call /reject with action_id: "action_1"
   → Rejects issue #2 (reason: not ready)

5. Call /execute
   → Writes approved actions to GitHub

6. Call /status
   → Shows: 0 pending, 1 approved, 1 rejected, 1 executed
```

---

## Monitoring & Logs

### View Deployment Status

```powershell
gcloud run services describe github-triage-agent --platform managed --region us-central1
```

### View Logs

```powershell
gcloud run services logs read github-triage-agent --platform managed --region us-central1 --limit 50
```

### View Metrics

In Google Cloud Console:
1. Go to **Cloud Run** → **Services**
2. Click on your service
3. View requests, latency, errors in the **Metrics** tab

---

## Billing

**Always free (Cloud Run always-free tier):**
- 2M invocations/month
- 360K GB-seconds/month
- 1M requests to other Google APIs

**You'll likely stay in the free tier** since your agent only runs when called.

---

## Environment Variables

**Important:** Never commit `.env` to git.

Cloud Run reads environment variables from `app.yaml`:

```yaml
env_variables:
  ANTHROPIC_API_KEY: "sk-ant-..."
  GITHUB_TOKEN: "ghp_..."
  GITHUB_REPO: "owner/repo"
```

**For production:** Use Google Secret Manager (Phase 4 can add this).

---

## Common Issues & Solutions

### Issue: "Resource not accessible by personal access token"

**Symptom:**
```
Error code: 403
{"message": "Resource not accessible by personal access token", ...}
```

**Solution:**
1. Check GitHub token has `repo` + `issues` scopes
2. Regenerate token if old
3. Update `.env` and redeploy:
   ```powershell
   gcloud run deploy github-triage-agent --source . ...
   ```

---

### Issue: "Service unavailable" on first request

**Symptom:**
```
HTTP 500: Service unavailable
```

**Solution:**
- Cloud Run is starting up (cold start)
- Retry after 10 seconds
- Look at logs: `gcloud run services logs read github-triage-agent`

---

### Issue: "Timeout" on /triage endpoint

**Symptom:**
```
HTTP 504: Deadline Exceeded
```

**Root cause:** Classifying many issues takes time

**Solution:**
- Increase timeout in app.yaml: `timeout: 600` (10 min)
- Reduce `limit` in request: `{"limit": 3}` instead of 10

---

### Issue: Memory exceeded

**Symptom:**
```
Container failed to start
```

**Solution:**
- Increase memory: `--memory 1Gi` (default is 512Mi)
- Redeploy with larger memory allocation

---

## Scaling & Performance

**Default settings** (from deployment script):
- Memory: 512 MB (enough for most use cases)
- Timeout: 300 seconds (5 minutes)
- Max instances: 10 (auto-scales)

**For heavy use:**
- Increase memory to 1 GB
- Increase max instances
- Use Cloud Tasks for async queuing

---

## Next Steps

**Phase 4 adds:**
- Golden dataset for evaluation
- LLM-as-a-judge scoring
- Code-level guardrails
- Performance metrics

See `PHASE_4.md` for details.

---

## Deployment Checklist

Before deploying:

- [ ] `.env` file exists with all required keys
- [ ] `gcloud` CLI authenticated
- [ ] Project ID is correct
- [ ] `main.py` runs locally without errors
- [ ] All files present (main.py, app.yaml, requirements.txt, src/*, config/*)
- [ ] Git is ignored `.env` (in `.gitignore`)

After deployment:

- [ ] Service appears in Cloud Run console
- [ ] Health endpoint returns 200
- [ ] `/triage` returns issues
- [ ] Approvals work end-to-end
- [ ] GitHub API can write (test with real issue)
- [ ] Logs show no errors

---

## Files Reference

| File | Purpose |
|------|---------|
| `main.py` | Flask REST API server |
| `app.yaml` | Cloud Run configuration |
| `deploy.sh` | Deployment automation script |
| `requirements.txt` | Python dependencies (with Flask/gunicorn) |
| `src/agent.py` | Classification logic (unchanged) |
| `src/tools.py` | GitHub API wrapper (unchanged) |
| `src/hitl_gate.py` | Approval gate (unchanged) |

---

## Summary

**Phase 3 transforms your local agent into a deployed service:**

```
Local CLI
  ↓
REST API on Cloud Run
  ↓
Accessible from anywhere
  ↓
Auto-scaling, always running
  ↓
Free tier covers typical usage
```

**You now have:**
- ✅ Issue classification service
- ✅ Human approval workflow
- ✅ Hosted REST API
- ✅ Audit trails

**Next:** Phase 4 adds evaluation and guardrails.