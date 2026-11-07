# Phase 4: Evals, Guardrails and Tracing

GitHub Issue Triage Agent (capstone). Written 2026-11-04, updated 2026-11-07.
Phases 1 to 3 are in `Phase1.md` to `Phase3.md`. There is no separate handoff file: this document is the record of Phase 4, and the work still open is listed in section 10.

## Start here

**What this is.** An agent that reads GitHub issues, classifies them with Claude, and proposes labels and a comment. A human approves each proposal. Only then does anything get written to GitHub.

**Status (2026-11-07).** Deployed and working as revision `github-triage-agent-00012-bzd`. The live `/triage` smoke test returned 5 of 5 proposals. The evals pass 99/99 over 33 cases x 3 runs (g18 is a known limitation, 0/3), and the judged run was 32/33 before one test note was loosened (section 5, finding B). Open: the deterministic guardrails and tracing of the judge. Section 10 has the full list.

**Reading order.**
- New to the project: follow **Getting started: step by step** right below this section, then use the numbered sections for detail.
- To run it: section 0 (setup, environments, safety), then section 7 (commands), then section 13 (troubleshooting).
- To understand it: section 4 (architecture), section 3 (metrics), section 12 (dataset schema).
- To review what happened: sections 2, 5 and 6 (results, bugs, learnings).
- Terms you do not know: section 14 (glossary).

**5-minute health check.** Run these from the repo root. If all three behave, your setup works.

```bash
python3 -m pytest tests -q                                  # 12 passed (these tests do not call the model)
python3 evals/run_eval.py --ids g01,g02 --tag healthcheck   # 2/2 pass, about 2 API calls
PORT=8081 python3 main.py                                   # then call /health and /triage (section 7)
```


---

## Getting started: step by step

This walkthrough takes you from a fresh clone to your first eval, your first local run and a check of the live service. Do the steps in order and compare each result with the "You should see" line. If a step does not match, stop and use section 13 (troubleshooting) before going on.

### Step 0: what you are looking at

The agent reads open GitHub issues, asks Claude to classify each one, and proposes labels and a comment. Nothing is written to GitHub until a person approves a proposal by its id and then triggers the write.

| Path | What it does |
|---|---|
| `src/agent.py` | Classification and orchestration. `classify_issue` is the heart of it |
| `src/tools.py` | GitHub API wrapper. The only code that writes to GitHub |
| `src/hitl_gate.py` | The approval gate. Proposals are tracked and approved by id |
| `src/guardrails.py` | Label vocabulary enforcement |
| `src/tracing.py` | Optional Langfuse tracing. Never breaks the agent if Langfuse is down |
| `config/prompts.py` | System prompt: label rules and comment rules |
| `main.py` | Flask API: `/health`, `/status`, `/triage`, `/approvals`, `/approve`, `/reject`, `/execute` |
| `evals/` | Golden dataset, eval runner, LLM judge and its calibration set |
| `tests/` | 12 unit tests. They do not call the model |
| `Phase1.md` to `Phase4.md` | One document per phase. This file is the newest |
| `NOTES.md` | Working notes |

### Step 1: get the code and install

```bash
git clone https://github.com/sridharkesavan/capstone-github-triage-agent.git
cd capstone-github-triage-agent
git branch --show-current
python3 --version
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
```

You should see: the branch is `master` (not `main`) and Python is 3.12. The repo is private, so you need access to it first. `google-adk` is in `requirements.txt` but is not used.

### Step 2: create your `.env`

Create a file named `.env` in the repo root. It is gitignored. Never commit it and never paste its contents into a chat or a ticket.

```
ANTHROPIC_API_KEY=...
GITHUB_TOKEN=...
GITHUB_REPO=sridharkesavan/ai-agents-from-scratch
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://jp.cloud.langfuse.com
```

- `ANTHROPIC_API_KEY` is needed for the agent and the evals.
- `GITHUB_TOKEN` (personal access token, `repo` scope) is needed for `/triage` and `/execute`, not for the evals.
- `GITHUB_REPO` is the repo whose **issues** get triaged. It is not the code repo. Pointing it at the code repo gives "No issues to triage".
- The Langfuse lines are optional. Without valid keys the agent still works and tracing is skipped. Real keys start with `pk-lf-` and `sk-lf-`. The project is in the Japan region, so keys from another region return 401.

### Step 3: run the unit tests

```bash
python3 -m pytest tests -q
```

You should see: `12 passed`. These tests do not call the model, so they cost nothing.

### Step 4: run two eval cases

```bash
python3 evals/run_eval.py --ids g01,g02 --tag healthcheck
```

You should see: `g01 PASS 1/1` and `g02 PASS 1/1`, a summary with `Fallback answers : 0 of 2`, and a line `Saved: evals/results/run_<timestamp>_healthcheck.json`. This makes 2 model calls and costs about two cents. It does not touch GitHub.

### Step 5: read one real reply

A score is not enough. Print what the agent actually said for g01 and g02:

```bash
python3 - <<'PY'
import json, glob
path = sorted(glob.glob("evals/results/*healthcheck.json"))[-1]
for r in json.load(open(path))["runs"]:
    res = r["result"]
    print(r["id"], "|", res["classification"], "|", res["suggested_labels"])
    print(res["response_comment"])
    print("-" * 60)
PY
```

You should see a classification, labels from the 7-label vocabulary (`bug`, `enhancement`, `question`, `documentation`, `duplicate`, `needs-triage`, `needs-more-info`) and a short comment that ends with "A maintainer will review this." Get into the habit of reading replies. In this phase a passing case hid a wrong comment (finding A), and a failing case turned out to be a bad test note (finding B).

### Step 6: run the API locally

```bash
PORT=8081 python3 main.py > /tmp/triage_local.log 2>&1 &
SERVER_PID=$!
sleep 6
curl -s http://localhost:8081/health
```

You should see: `{"agent_initialized":true,"executions":0,"pending_approvals":0,"status":"healthy"}`. Port 8081 leaves 9090 free for the Cloud Run proxy (step 11). Stop the server with `kill $SERVER_PID` when you are done.

### Step 7: make the agent triage one issue

```bash
curl -s -X POST http://localhost:8081/triage -H "Content-Type: application/json" \
  -d '{"repo": "sridharkesavan/ai-agents-from-scratch", "limit": 1}'
```

You should see JSON with `issues_found: 1`, `proposed: 1`, `warning: null` and an `approvals` object keyed by an 8-character action id. `/triage` only creates in-memory proposals. Every run clears the earlier proposals, and the ids change each time. If `issues_found` is greater than 0 and `proposed` is 0, the response carries a `warning`: look for `[SKIP]` lines in `/tmp/triage_local.log`.

### Step 8: understand the approval flow (read first, do not run casually)

```
POST /triage                    creates proposals (in memory only)
GET  /approvals                 lists them with their ids
POST /approve {"action_id": ""} marks one approved
POST /reject  {"action_id": ""} marks one rejected
POST /execute                   writes the approved ones to GitHub
```

Put a real action id between the quotes. **`/execute` writes real labels and comments to the real repo in `GITHUB_REPO`.** Test issues #1 to #5 in `ai-agents-from-scratch` are real issues, so executing posts real comments there. Only approved ids can reach the write calls, and each approval executes once. That rule is enforced in code, not in the prompt, and `tests/test_gate_invariant.py` checks it.

### Step 9: run the full evals and read the output

```bash
python3 evals/run_eval.py
python3 evals/run_eval.py --judge
python3 evals/run_eval.py --repeat 3 --tag stability
```

- **Cost:** one classification is about $0.010 to $0.012. A full 34-case run is roughly $0.35 to $0.40 and `--repeat 3` roughly $1.10. The judge adds a call per comment and its cost has not been measured.
- **How to read it:** `CASE RESULTS` lists PASS, FAIL or FLAKY per case. `SUMMARY` gives the headline pass rate, the fallback count and a per-check table. FLAKY means the case passed some runs and failed others.
- **g18 fails every time on purpose.** It is a known limitation (an implicit duplicate the classifier cannot see, because it looks at one issue at a time) and is reported apart from the headline.
- **Reference numbers at the end of Phase 4:** 99/99 on the deterministic checks over 33 cases x 3 runs, none flaky; the judged run was 32/33 before g01's test note was loosened.
- Calibrate the judge itself with `python3 evals/judge.py --calibrate`. It should agree on 23 of 23 hand-written replies.

### Step 10: change something safely

Follow this routine for any change to the prompt, the parser, a guardrail or the dataset:

1. Run the evals **before** the change and keep the results file.
2. Change **one** thing. Keep the judge fixed while you change the prompt.
3. Run the evals again and compare. Read the replies that changed, not only the score.
4. If you edit the golden dataset, bump `version` and add a line to `changelog` saying what changed and why. Section 12 shows how to add a case.
5. Edit files with a guarded patch script (section 7, "Safe patch pattern"). It stops if an anchor is missing or appears twice.
6. Commit the code change and the dataset change that motivated it together, and check `git diff` first. Rewriting the JSON dataset can reformat hundreds of lines.

Facts GitHub already knows (issue number, title) come from code after parsing, never from the model. Keep it that way.

### Step 11: deploy and check the live service

```bash
git status --short
git push origin master && git log -1 --oneline origin/master
gcloud run deploy github-triage-agent --source . --region us-central1 \
  --project github-triage-agent-513401 --no-allow-unauthenticated --max-instances 1
```

The Langfuse secrets and host persist from the earlier deploy. The full command with secrets is in section 7. You need `gcloud` signed in with access to the project. The service is private, so reach it through a proxy. In a **second terminal tab** (it must keep running):

```bash
gcloud run services proxy github-triage-agent --region us-central1 --project github-triage-agent-513401 --port 9090
```

Back in the first tab:

```bash
curl -s http://localhost:9090/health
curl -s -X POST http://localhost:9090/triage -H "Content-Type: application/json" \
  -d '{"repo": "sridharkesavan/ai-agents-from-scratch", "limit": 5}'
gcloud run services describe github-triage-agent --region us-central1 --project github-triage-agent-513401 \
  --format="value(status.latestReadyRevisionName)"
```

A pass means: `proposed` equals `issues_found`, the issue numbers match the issues, labels are in the vocabulary and comments are under 800 characters. Smoke-test the **live** service after every deploy. In this phase, 26 passing evals sat next to a live service that proposed nothing (bug 5), and one `curl` found it.

To confirm the revision really contains your change, compare the revision's creation time (UTC) with the time of your last code commit (`git log -1 --date=iso-strict -- src config main.py Dockerfile requirements.txt`). The revision must be newer.

### Step 12: check the trace in Langfuse

Open `https://jp.cloud.langfuse.com`, go to Tracing and set the time filter to the last hour. Find the `classify_issue` trace whose timestamp matches your call (Cloud Run logs are in UTC, the dashboard follows your browser's timezone). You should see:

- the issue title and body in the input (the body is capped at 2000 characters);
- the model's raw JSON in the output. Its `issue_number` is `null` or `0`, because the model never sees the number. The code overwrites it, and this is the behavior behind bug 5;
- one `anthropic.messages.create` child with the tokens and a cost of about $0.01, and no cost on our own span;
- a nested pair of `classify_issue` spans. That is cosmetic.

An empty dashboard can mean tracing is disabled, because the wrapper hides errors by design. Run `auth_check()` (section 7, "Langfuse checks") before assuming the agent is the problem.

### Step 13: before you call a change done

- `python3 -m pytest tests -q` shows 12 passed.
- The full eval run shows no new failures, no new flaky cases and 0 fallbacks.
- You read the replies for every case your change touched.
- `git status --short` is empty and `git log -1 --oneline origin/master` shows your commit.
- If code changed, the service is redeployed, the smoke test passed and a fresh trace appeared.
- This document and `NOTES.md` say what is now true.

---

## 0. Before you run anything

### Prerequisites

- Python 3.12 (this project was developed on 3.12.0).
- `pip install -r requirements.txt`. Pinned: `anthropic==2.4.0`, `langfuse==3.0.0`, `PyGithub==2.1.1`, `python-dotenv==1.0.1`, `Flask==3.0.0`, `gunicorn==21.2.0`. `google-adk==0.1.0` is listed but not used.
- `pytest` is not in `requirements.txt`. If `python3 -m pytest` fails, run `pip install pytest`.
- `gcloud` CLI, only for deploying or reading Cloud Run logs. Docker is optional (there is no local container setup at the moment).
- A `.env` file at the repo root, never committed:

```
ANTHROPIC_API_KEY=...        # needed for the agent and the evals
GITHUB_TOKEN=...             # personal access token, repo scope; needed for /triage and /execute, not for evals
GITHUB_REPO=sridharkesavan/ai-agents-from-scratch
LANGFUSE_PUBLIC_KEY=pk-lf-...   # optional: tracing is skipped if these are missing or wrong
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://jp.cloud.langfuse.com
```

Real Langfuse keys start with `pk-lf-` and `sk-lf-`. Template placeholders cost several rounds of debugging (bug 8).

### Which endpoint is which

Most confusion in this phase came from not knowing which server a command hit (bug 7).

| Name | How to reach it | Runs | Notes |
|---|---|---|---|
| Local server | `PORT=8081 python3 main.py`, then `http://localhost:8081` | Your working copy | Reads real GitHub issues. Without `PORT` it listens on 8080 |
| Cloud Run through the proxy | `http://localhost:9090` | The **deployed** code | In `lsof -i :9090` the process is called `cloud-run`. It is most likely `gcloud run services proxy github-triage-agent --region us-central1 --project github-triage-agent-513401 --port 9090`. The exact command was not recorded, so confirm with `ps -p <pid> -o command=` |
| Cloud Run directly | `https://github-triage-agent-iiwatmpdza-uc.a.run.app` | The deployed code | Private (`--no-allow-unauthenticated`), so use the proxy |
| Langfuse | `https://jp.cloud.langfuse.com` | Traces | Japan region. Keys from another region return 401 |

If a result looks wrong, first ask which of these answered.

### What can write to GitHub

- `POST /triage` reads issues and creates **in-memory proposals only**. It clears any pending proposals from earlier runs first, and action ids change on every run.
- `POST /approve {action_id}` and `POST /reject {action_id}` only mark proposals.
- `POST /execute` writes labels and comments to the real repo in `GITHUB_REPO`. Test issues #1 to #5 in `ai-agents-from-scratch` are real issues, so executing against them posts real comments.
- The evals never write to GitHub. They skip the agent's GitHub connection on purpose.

---

## 1. Summary

Phase 4 asked one question: **can I trust this agent's output, and how would I know if it broke?**

What was built:

| Area | What exists now |
|---|---|
| Golden dataset | 34 cases (v5) in `evals/golden_issues.json`, every edit logged in `changelog` |
| Eval runner | `evals/run_eval.py`: deterministic checks, optional LLM judge, repeat runs, tags |
| Judge | `evals/judge.py`, calibrated against 12 hand-written replies (23/23 agreement) |
| Guardrails | Label vocabulary enforced in prompt and in code (`src/guardrails.py`) |
| Comment policy | Rules in `config/prompts.py`, checked by length, opening, closing and the judge |
| Tracing | Langfuse, optional and non-blocking (`src/tracing.py`), deployed to Cloud Run |
| API safety net | `/triage` warns when issues were classified but nothing was proposed (deployed in revision 00012; not yet seen firing, because every live run proposed all issues) |

Honest status (2026-11-07): the evals, the judge, tracing and the fixes in section 5 are done and deployed. The deterministic guardrails (approved-action write path, fallback block, link check, promise flag) and tracing of the judge are not written. Section 10 lists what is still open.

---

## 2. Results timeline

| Run | Result | What changed |
|---|---|---|
| Baseline (deterministic checks) | 2/26 (8%) | Nothing yet. 5 of 27 answers were silent parser fallbacks, labels were invented |
| After parser fix + label vocabulary | 26/26 (100%) | Stability: 9 hard cases x 3 runs = 27/27, none flaky. Injection case g23 resisted 4 of 4 |
| Judged comments, first run | 2/26 (8%) | 80% of comments too long, 80% made promises, 36% ungrounded |
| After comment policy prompt | 24/26 (92%) | Policy written into the system prompt |
| Dataset v3 + comment polish | 26/26 (100%) | Friendly opening, closing line in the reporter's language |
| Live smoke test (Cloud Run) | **0 proposals** | Passed every eval and still did nothing: the issue-number bug (section 5, bug 5) |
| After issue-number fix | 5/5 proposed | Numbers #1 to #5 correct, labels in vocabulary, comments under 800 characters |
| After null-body fix and 2000-character cutoff | g28 to g34 all pass | g29's comment names the real problem; see section 5, finding A |
| Full run, `--repeat 3`, 34 cases | 99/99 headline, g18 known limitation 0/3, no flaky cases, 0 fallbacks in 102 answers | Deployed as revision `00012-bzd`, live smoke test 5/5 |
| Judged run, 34 cases, one run each | 32/33 (g18 excluded) | g01 failed the judge's `addresses_issue` check |
| After g01 judge notes (dataset v5) | g01 3/3 judged | The test note was loosened, the agent was not changed; see finding B |

The 26/26 score and the broken live service existed at the same time. That is the main lesson of the phase.

---

## 3. Metrics and formulas

All of these are how the numbers in this document were computed.

| Metric | Definition |
|---|---|
| Case passes | `all(checks.values())`: every check for that case is true |
| Headline pass rate | `passing cases / scored cases`. Cases marked `known_limitation` are reported separately (g18, implicit duplicate), which is why 27 cases gave "26/26" |
| Per-check rate | `cases where the check is true / cases where the check ran` |
| Fallback rate | `answers where is_fallback(res) / total answers`. Fallback means a parse failure, an API error, or the canned "Default classification due to parsing error" reply |
| Stability | Run each case N times (`--repeat 3`). A case is **flaky** if its pass/fail result differs between runs. 9 hard cases x 3 = 27 runs, 27 passed |
| Label vocabulary check | `set(labels + dropped_labels) <= vocabulary`. It uses the **raw** model output (kept labels plus the ones the guardrail dropped), so the guardrail cannot hide a model that tried to invent labels |
| Comment length | `len(comment) <= 800` characters |
| Cold opening | The comment starts with a pattern such as "This report..." (`BAD_OPENING`). Count went from 16 of 26 to 0 of 25 |
| Closing in reporter language | If title + body contain Japanese, the last non-empty line of the comment must contain Japanese. Went from 2 of 2 failing to 0 |
| Issue identity (new) | `res["issue_number"] == int(case_id[1:])` and `res["issue_title"] == case["title"]` |
| Judge agreement | `verdicts matching a human label / total verdicts` on `evals/judge_calibration.json`: 23/23 |
| Zero-proposal warning | `issues_found > 0 and proposed == 0` |
| Cost per classification | About $0.010 to $0.012 (claude-opus-5-5, about 2k tokens). Trace cost = sum of costed observations, which must count each API call once |

---

## 4. Architecture at the end of Phase 4

```
GitHub issues
   -> classify_issue (Claude)           traced in Langfuse as a span
   -> issue_number / issue_title set from GitHub in code   <- added this phase
   -> enforce_label_vocabulary          guardrail
   -> propose_github_action             skips if issue_number is falsy
   -> HUMAN approves by action id
   -> write to GitHub
```

Files touched in Phase 4:

| File | Role |
|---|---|
| `src/agent.py` | Classification; now sets identity from GitHub, carries `@observe` and the trace update |
| `src/guardrails.py` | `enforce_label_vocabulary`, `DEFAULT_LABEL = "needs-triage"` |
| `src/tracing.py` | Optional Langfuse wrapper: `observe`, `update_generation`, `flush` |
| `config/prompts.py` | System prompt with label rules and comment rules |
| `main.py` | Flask API; `flush()` before the `/triage` response; zero-proposal warning |
| `evals/golden_issues.json` | Dataset v5, 34 cases |
| `evals/run_eval.py` | Runner and `score()` |
| `evals/judge.py`, `evals/judge_calibration.json` | LLM judge and its calibration set |
| `requirements.txt` | `anthropic==2.4.0` now pinned |

Label vocabulary (7): `bug`, `enhancement`, `question`, `documentation`, `duplicate`, `needs-triage`, `needs-more-info`.

Comment policy: acknowledge the issue, short hints grounded in the issue, ask for missing details, "A maintainer will review this." is allowed, no specific promises (fix, reopen, close, add docs, timelines), under 800 characters, reply in the reporter's language, no facts about the project that the issue does not state. Japanese issues get a Japanese reply that ends with "担当者が確認します。"

---

## 5. Bugs and how they were cleared

### Bugs in the agent

**Bug 1: JSON parser silently returned a generic answer**
- Symptom: baseline 2/26. 5 of 27 results were fallbacks.
- Cause: the parser split the reply on the first code fence, which cut off any reply whose comment contained a code block, then fell back to a generic "question" answer.
- Fix: take everything from the first `{` to the last `}`.
- Found by: evals. Silent misclassification of live issues.

**Bug 2: labels were unconstrained**
- Symptom: the model invented labels (for example a forbidden label in the injection case).
- Fix: two layers. The prompt lists the allowed labels, and `enforce_label_vocabulary` removes anything else and records it in `dropped_labels`. If nothing valid is left, it falls back to `needs-triage`.
- Lesson: the eval checks the raw labels, so it still notices a model that tries.

**Bug 3: comments were too long, made promises, and invented facts**
- Symptom: judged run 2/26 (80% too long, 80% promises, 36% ungrounded).
- Fix: comment policy in the prompt (section 4). 24/26 after the policy, 26/26 after dataset v3 and the polish step.
- Two failing cases were bad test notes, not agent faults. The notes demanded exact wording, so they were loosened to describe intent and the change was logged in the changelog.

**Bug 4: approval gate wrote to the wrong issue (Phase 3, kept here as a lesson)**
- Symptom: approved #4, rejected #3, and `/execute` wrote to #3.
- Cause: position-based approvals.
- Fix: id-based gate (`Action.id`, `approve_by_id`, `reject_by_id`, `pop_approved`, `clear_pending`) plus `tests/test_gate_invariant.py`.

**Bug 5: `/triage` proposed nothing (found by a live smoke test, not by the evals)**
- Symptom: `issues_found: 5, proposed: 0, status: success`.
- How it was narrowed down: raw response had no error field -> container logs -> `[SKIP] Cannot propose action: issue number is null` for every issue -> `grep issue_number` -> the prompt's JSON schema asks the model for `issue_number` -> a Langfuse trace later showed the reply `"issue_number": 0` with the reasoning "the issue number was not provided, so 0 is a placeholder".
- Cause: the model never sees the issue number, so it returns 0 or null. `json.loads` replaced the whole result with the model's JSON, and `propose_github_action` skips falsy numbers.
- Danger beyond the zero proposals: if the model had guessed a plausible number, the gate would have shown a clean proposal for the **wrong issue**.
- Fix (commit `8ed4623`): right before the guardrail call, set `classification["issue_number"] = issue["number"]` and `classification["issue_title"] = issue["title"]`. This covers both parsed and fallback results.
- Why the evals missed it: they checked labels and comments and never checked identity. Fixed by the new `issue_number_matches` and `issue_title_matches` checks.

**Bug 6: null body crashes `classify_issue` (fixed 2026-11-07)**
- Symptom: `TypeError: 'NoneType' object is not subscriptable` at `body=issue['body'][:500]` when running new case g28 (body is `null`). It aborted the whole eval run, so no results file was saved.
- Cause: the prompt is built before the `try:` block, so the exception is not caught and no fallback is returned.
- Live service: **not affected**. Both fetch paths in `src/tools.py` use `issue.body or ''`.
- Fix: `body=(issue.get('body') or '')[:2000]` and the prompt building moved inside the `try`, so a prompt error becomes a fallback instead of aborting a run. g28 now passes with a sensible reply (bug, needs-more-info, asks for details). The cutoff went from 500 to 2000 characters in the same session (finding A).

### Findings from the judged runs (2026-11-07)

**Finding A: the 500-character cutoff made a comment blame the reporter (g29)**
- Symptom: g29 passed every check. Its comment asked for the status code, the failing ids and the error text, and said the description "seems to have been cut off".
- Cause: the real problem (`POST /approve` returns 500 with `KeyError 'action_id'` for uppercase ids) sat past character 500. The model never saw it, and the cut was ours, not the reporter's.
- Fix: cutoff raised to 2000 characters. The comment then named the uppercase-id problem and `needs-more-info` was dropped. Full 34-case run, 3 repeats: no case changed behavior.
- Still open: there is no "[body truncated]" marker, so a body over 2000 characters can still produce the same wording.

**Finding B: g01 flipped under the judge (the agent varied, the judge did not)**
- Symptom: judged run 32/33, with g01 failing `addresses_issue`. Repeated x3: 2/3.
- Reading the comments: the two passing comments asked for the raw model response. The failing one acknowledged the traceback and offered a hypothesis but asked for nothing. The judge gave the same verdict for the same kind of comment every time.
- Decision: added `judge_notes` to g01 (dataset v5): a complete report may need no request for details, and one useful extra request is also fine. Prompt and judge unchanged. g01 then passed 3/3.
- Honest reading: this loosened the test. It did not change the agent, which still varies between the two comment styles.
- Judge blind spot, seen on g34: the judge passed a comment asking for error messages on a documentation request, because it checks for invented claims, not for questions that fit the issue.

### Bugs in the tooling and process

| # | Symptom | Cause | How it was cleared |
|---|---|---|---|
| 7 | "Local Docker test" returned 0 proposals | Nothing from the capstone was running in Docker. Port 9090 was held by `cloud-run` (the `gcloud run services proxy`), so the test hit the live service | `docker ps -a; lsof -i :9090` showed it. Local server now runs on `PORT=8081`, proxy stays on 9090 |
| 8 | Langfuse `401 Invalid credentials` | `.env` held template placeholders (`your-la...`, 24 chars), then `LANGFUSE_HOST` was empty. The tracing wrapper hid the failure | Print only the first 7 characters and length of each key, create a new key pair, set the host. `auth_check()` returned True |
| 9 | Langfuse host confusion | The project is on the Japan region: `https://jp.cloud.langfuse.com` | Found by reading `.env`. Handoff docs had listed the EU host |
| 10 | Duplicate tracing code in `agent.py` (two imports, two decorators) | The patch script ran twice | `git checkout src/agent.py`, re-ran a patch that stops with "already patched" |
| 11 | Trace cost counted twice ($0.024 for one call) | Anthropic SDK 2.4.0 emits its own `anthropic.messages.create` span with tokens and cost. Our generation added `usage_details`, so it was costed too | Removed `usage_details` (total fell to $0.014, because Langfuse then estimated tokens for our generation), then changed our observation to `as_type="span"` (total $0.012, one cost) |
| 12 | Patch script aborted, nothing changed | The anchor `model=self.model,` appeared twice in `agent.py` | The script asserts each anchor matches exactly once before writing, so it failed safely. Used a longer, unique anchor |
| 13 | `zsh: no matches found: --include=*.py` | zsh expands the glob itself | Quote it: `--include="*.py"` |
| 14 | `load_dotenv()` raised `AssertionError` in a heredoc script | It cannot find `.env` without a file path | `load_dotenv(".env")` |
| 15 | Wrong belief that Phase 4 commits were unpushed | Read the stale `origin/main` ref. The branch is `master` and `origin/master` already had them | `git log -1 --oneline origin/master` |
| 16 | Build failure in an earlier phase: `Client.__init__() got an unexpected keyword argument 'proxies'` | Old `anthropic` pinned with a newer `httpx` in a clean build. It only worked locally because an upgraded copy was installed | `anthropic>=0.50.0`, now pinned to `anthropic==2.4.0` (built cleanly on Cloud Run) |

---

## 6. Learnings

1. **A passing score and a correct system are different things.** 26/26 evals coexisted with a service that proposed nothing. The harness had no check for the one fact the approval gate depends on.
2. **Facts that GitHub already knows come from code, never from the model.** Issue number and title are set after parsing.
3. **A silent total failure is a guardrail gap.** `status: success` with zero proposals hid a bug for the whole of the eval work.
4. **Error-swallowing wrappers make failures invisible.** The tracing wrapper must never break the agent, but that also means an empty dashboard can mean "disabled". Verify with `auth_check()` and the dashboard, not with "the agent still works".
5. **Test the test harness.** The judge was calibrated (23/23). Two failing cases were bad test notes. The new identity check should be shown to fail on a wrong number before it is trusted.
6. **Change one thing at a time.** Keep the judge fixed while changing the prompt. Log every dataset edit with a reason.
7. **Deterministic guardrails sit on top of the model, not instead of it.** The vocabulary is in the prompt and in code, and the eval checks the raw output.
8. **Patch scripts need guards.** Anchors that must match exactly once, and an "already patched" check, turned two accidents into harmless failures.
9. **Read the real output before trusting it.** Several wrong guesses in this phase (the double patch as the cause of nested spans, the null-body handler, the stale `origin/main` ref) were corrected only because the output was pasted back.
10. **"Works on my machine" is not a fix.** The Docker build exposed the anthropic/httpx conflict, and a local environment with extra packages installed can show traces the container will not produce.
11. **Eval a real failure end to end.** The most valuable test in the phase was not an eval. It was one `curl` against the live service.
12. **A passing case can still carry a wrong reply.** g29 passed every check while its comment blamed the reporter for a cut that our own 500-character limit made. Read the reply, not only the score.
13. **A consistent judge on an underspecified case measures the rubric, not the agent.** g01 flipped because the agent sometimes asked for the raw model response and sometimes did not, and the judge graded each style the same way every time. The fix was a test note stating the intent. That makes the case pass; it does not make the agent more consistent, and the write-up should say so.

---

## 7. Commands

### Evals

```bash
# Deterministic checks on all cases
python3 evals/run_eval.py

# Add the comment policy checks and the LLM judge
python3 evals/run_eval.py --judge

# Specific cases, repeated runs, a name for the results file
python3 evals/run_eval.py --ids g19,g23 --repeat 3 --tag stability

# Other flags: --workers N (parallel API calls, 4 by default), --model (must match src/agent.py), --judge-model (defaults to --model)

# Calibrate the judge itself
python3 evals/judge.py --calibrate

# Unit tests (12; they do not call the classifier)
python3 -m pytest tests -q
```

Results go to `evals/results/` (gitignored except `*_baseline.json`).

Each results file is JSON with these top-level keys: `timestamp`, `model`, `judge_model`, `repeat`, `cases_run`, `headline`, `fallbacks`, `runs`. The per-case, per-run detail is under `runs`; open one file to see its exact shape.

### Run the API locally (port 8081, leaves the Cloud Run proxy on 9090)

```bash
PORT=8081 python3 main.py > /tmp/triage_local.log 2>&1 &
SERVER_PID=$!
sleep 6
curl -s -X POST http://localhost:8081/triage -H "Content-Type: application/json" \
  -d '{"repo": "sridharkesavan/ai-agents-from-scratch", "limit": 1}' \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print('proposed:', d.get('proposed'), '| warning:', d.get('warning'))"
sleep 10
kill $SERVER_PID
```

`/triage` only creates proposals. Nothing is written to GitHub unless someone calls `/approve` and `/execute`.

### Smoke test the live service (through the proxy on 9090)

```bash
curl -s -X POST http://localhost:9090/triage -H "Content-Type: application/json" \
  -d '{"repo": "sridharkesavan/ai-agents-from-scratch", "limit": 5}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('issues_found:', d.get('issues_found'), 'proposed:', d.get('proposed'))
for k, v in d['approvals'].items():
    print(k, '| #', v['issue_number'], '|', v['labels'], '|', len(v['comment'] or ''), 'chars')
"
```

A pass: `proposed` equals `issues_found`, the numbers match the titles, labels are in the vocabulary, comments are under 800 characters.

### Diagnose a quiet failure

```bash
# What is on port 9090, and is anything running in Docker?
docker ps -a; lsof -i :9090

# Live service logs
gcloud run services logs read github-triage-agent --region us-central1 --project github-triage-agent-513401 --limit 40

# Where is a key read or written?
grep -n "issue_number\|'number'" src/agent.py src/guardrails.py main.py
```

### Deploy

```bash
gcloud run deploy github-triage-agent --source . --region us-central1 \
  --project github-triage-agent-513401 --no-allow-unauthenticated --max-instances 1 \
  --update-secrets LANGFUSE_PUBLIC_KEY=langfuse-public-key:latest,LANGFUSE_SECRET_KEY=langfuse-secret-key:latest \
  --update-env-vars LANGFUSE_HOST=https://jp.cloud.langfuse.com
```

Check what is deployed (prints no secret values):

```bash
gcloud run services describe github-triage-agent --region us-central1 --project github-triage-agent-513401 \
  --format="yaml(status.latestReadyRevisionName,status.traffic,spec.template.spec.containers[0].env)"
```

### Secrets (read from `.env` without printing; `printf` avoids a trailing newline)

```bash
for k in LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY; do
  v=$(python3 -c "from dotenv import dotenv_values; print(dotenv_values('.env')['$k'], end='')")
  name=$(echo $k | tr 'A-Z_' 'a-z-')
  printf "%s" "$v" | gcloud secrets create $name --data-file=- --project github-triage-agent-513401
done
gcloud secrets list --project github-triage-agent-513401
```

### Langfuse checks

```bash
# Credentials and host (prints True or raises 401)
python3 -c "
from dotenv import load_dotenv; load_dotenv('.env')
from langfuse import get_client
print('auth_check:', get_client().auth_check())
"

# Look at .env without exposing keys: first 7 characters and length
python3 - <<'EOF'
from dotenv import dotenv_values
v = dotenv_values(".env")
for k in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]:
    x = v.get(k) or ""
    print(k, "->", x[:7] if "KEY" in k else x, "| length", len(x))
EOF
```

Real keys start with `pk-lf-` and `sk-lf-` and are 42 characters here. Placeholder keys were 24 characters.

### Safe patch pattern (used all through the phase)

```python
s = open(path).read()
assert "marker of the change" not in s, "already patched"
assert s.count(anchor) == 1, f"anchor: found {s.count(anchor)}"
open(path, "w").write(s.replace(anchor, new))
```

### Git

```bash
git status --short
git log -5 --oneline
git push origin master && git log -1 --oneline origin/master    # branch is master, not main
```

---

## 8. Langfuse tracing: how it is wired

- `src/tracing.py` imports Langfuse in a `try`. If the import fails, `observe` becomes a no-op decorator and `update_generation` / `flush` do nothing. The agent never depends on Langfuse.
- `classify_issue` is decorated with `@observe(name="classify_issue", as_type="span", capture_input=False, capture_output=False)`. After the model reply is read, `update_generation(...)` attaches the prompt, the raw reply, and metadata (`model`, `issue_number`, `stop_reason`).
- Token usage and cost come from the Anthropic SDK's own `anthropic.messages.create` child span, so cost is counted once.
- `flush()` runs at the end of `/triage` so buffered traces are sent before Cloud Run can freeze the instance.
- The Langfuse project is in the Japan region. Keys are in `.env` locally and in Secret Manager on Cloud Run.
- Known cosmetic point: the tree shows a nested `classify_issue` pair. Left alone.
- Not yet traced: the judge call and each eval run (planned: tag by case id).

---

## 9. State at the end of the phase

| Item | State |
|---|---|
| Issue-number fix | Done, pushed, deployed, live smoke test passed (5/5) |
| Langfuse tracing | Done locally and deployed (now revision `github-triage-agent-00012-bzd`). A second Cloud Run `/triage` call produced a fresh trace |
| Identity checks in `run_eval.py` | Shown to fail on issue number 0, None, 2 and "1" (a string) and on a wrong title, each failing only its own check (2026-11-07) |
| Dataset v5 (34 cases) | Committed and pushed (`89b58ae`). g28 to g34 pass; g01 got `judge_notes` in v5 |
| `/triage` zero-proposal warning | In `main.py`, committed (`4ab14fb`), deployed in revision 00012. Not yet seen firing: every live run proposed all issues |
| Uncommitted | Nothing. Code, data and this write-up are committed and pushed |

---

## 10. What is not done

1. **Done 2026-11-07.** Bug 6 fixed, g28 to g34 re-run and read, g29 cutoff raised to 2000 characters.
2. **Done 2026-11-07.** Eval changes committed (`d611f05`, `89b58ae`), redeployed as revision 00012, smoke test 5/5.
3. **Partly done.** `--repeat 3` on 34 cases without `--judge`: 99/99, none flaky. `--judge` once on 34: 32/33, then the g01 note. Not yet run: `--judge --repeat 3` on the full set.
4. Remove `issue_number` and `issue_title` from the prompt's JSON schema (the model cannot know them). Separate change, run the eval before and after.
5. Add a golden case with a complete bug report that must **not** get `needs-more-info`. Every live test issue got that label. The test issues really are thin (14 to 140 characters), so it was correct, but over-triggering is untested.
6. Deterministic guardrails still to write: `GitHubTools` write methods that refuse unless given an approved action, block proposals made from fallback results, a link check on comments, a promise-phrase flag, a length cap.
7. Trace the judge call and each eval run in Langfuse.
8. Remove `google-adk==0.1.0` from `requirements.txt` (unused).
9. Optional later: spam/invalid category, persistent approvals (Firestore), append-only audit log, port to Google ADK with the eval suite as a safety net, then the enterprise simulation.

### Known limitations

- Pending approvals live in memory and reset when the instance scales to zero, so Cloud Run runs one instance with one gunicorn worker.
- `approval_log.json` is overwritten on each execute.
- A failed classification still looks like a normal proposal until a guardrail blocks it.
- Spam has no category. Test issues #4 and #5 got labels but no comment.
- Issues #1 and #2 have identical bodies, so they are poor fixtures for comment quality.
- Implicit duplicates (g18) are out of reach because the classifier sees one issue at a time.
- The judge is the same model family as the agent (self-grading bias) and was calibrated on clear-cut examples.
- The dataset was drafted by the assistant and reviewed by the owner, one run per case.
- The judge does not check whether the questions in a comment fit the issue (g34 asks about error messages on a documentation request) and passes any comment that makes no invented claim.
- g01's judge note was loosened after the judged run flipped. The agent still varies between a bare acknowledgement and a request for the raw model response.
- The judge has run once per case on the full set. Only g01 was repeated.

---

## 11. One-line takeaways for the write-up

- Evals found two production bugs (the parser and the invented labels). A live smoke test found a third (the issue number) after the evals passed 26/26. The harness then got the check it was missing.
- A trace showed the model's own words: "so 0 is a placeholder".
- Make the system fail loudly, and test the thing that tests the system.

---

## 12. Golden dataset: schema and how to add a case

`evals/golden_issues.json` has these top-level keys: `version`, `changelog` (a list of strings), `description`, `label_vocabulary`, `fields` (documents the case fields), `cases`.

Case fields:

| Field | Meaning |
|---|---|
| `id` | `g` followed by an integer, for example `g28`. **The integer is used as the issue number** (`int(id[1:])`), and the identity check compares the agent's reply against it, so keep this format |
| `tags` | Free labels used for the "By tag" summary |
| `title`, `body` | The issue text. `body` may be `null` (case g28) |
| `acceptable_classifications` | Classifications that count as correct. `null` means the classification is not scored |
| `labels_required` | Labels that must appear in `suggested_labels` |
| `forbidden_labels` | Labels that must never appear (optional) |
| `comment_required` | Whether the proposal must include a comment |
| `forbidden_in_comment` | Strings that must not appear in the comment (optional) |
| `judge_notes` | What a good comment must do. Used only by the LLM judge (optional) |
| `known_limitation` | A case the current design cannot solve. Reported separately from the headline (optional) |

Example (g01):

```json
{
  "id": "g01",
  "tags": ["bug", "clear"],
  "title": "KeyError: 'issue_number' when model returns incomplete JSON",
  "body": "Running /triage on a repo with an empty-body issue crashes with: ...",
  "acceptable_classifications": ["bug"],
  "labels_required": ["bug"],
  "comment_required": true
}
```

To add a case:

1. Append it to `cases` with the next free id. Keep `judge_notes` about intent, not exact wording (v3 loosened two cases for demanding specific phrasings).
2. Bump `version` and add a line to `changelog` saying what changed and why. Every dataset edit gets logged.
3. Run only that case: `python3 evals/run_eval.py --ids g35 --tag new_case`.
4. **Read the actual reply**, not only the score. A passing result can hide a wrong reply, and a failing one can be a bad test note.
5. Commit the dataset and the code change that motivated it together.

Caution: rewriting the file with `json.dump(..., indent=2)` changed about 500 lines in v4 (formatting, not content). Check `git diff` before committing.

---

## 13. Troubleshooting: symptom, first command

| Symptom | First thing to run | Usual cause |
|---|---|---|
| `/triage` returns `proposed: 0` | `gcloud run services logs read github-triage-agent --region us-central1 --project github-triage-agent-513401 --limit 40` and look for `[SKIP]` lines | Issue number falsy (bug 5), or no labels or comment (see the warning field once it is deployed) |
| "No issues to triage" | `grep GITHUB_REPO .env` | `GITHUB_REPO` points at the code repo, not the repo with the issues |
| Langfuse `401 Invalid credentials` | The `auth_check` command in section 7 | Placeholder keys, an empty `LANGFUSE_HOST`, or keys from a different region |
| No traces in the dashboard | `auth_check`, then set the time filter to the last hour and wait a minute | The tracing wrapper hides errors by design. Make sure `flush()` runs at the end of `/triage` |
| Trace cost is doubled | Look at the tree in Langfuse | Our observation must be `as_type="span"` and must not pass `usage_details`; the SDK's `anthropic.messages.create` child carries the cost |
| Eval run crashes with a traceback | Read the last frame and the case id | One raising case aborts the whole run and **no results file is saved** (bug 6). Run the others with `--ids` while you fix it |
| `ANTHROPIC_API_KEY not found` | `ls -a` in the repo root | `.env` must be at the repo root |
| `ANTHROPIC_API_KEY not set` on Cloud Run | `gcloud secrets list --project github-triage-agent-513401` | Secrets were never created, or the key was pasted with a newline |
| Build error `unexpected keyword argument 'proxies'` | `grep anthropic requirements.txt` | An old `anthropic` with a newer `httpx` in a clean build |
| Approve and execute disagree | `python3 -m pytest tests -q` | Position-based approvals. The gate is id-based now |
| `zsh: no matches found: --include=*.py` | Quote the glob: `--include="*.py"` | zsh expands the pattern itself |
| A patch script stops with `AssertionError` | Read the message | `already patched`, or an anchor matched zero or several times. This is the guard working |

---

## 14. Glossary and files to ignore

| Term | Meaning here |
|---|---|
| HITL | Human in the loop. Nothing is written to GitHub until a person approves the proposal by action id |
| Proposal / action | An in-memory record of labels and a comment for one issue, waiting for approval |
| Guardrail | Plain code that checks or limits the model's output (for example the label vocabulary) |
| Fallback | The canned reply `classify_issue` returns when parsing fails or the API call errors. Counted separately by the evals |
| Golden dataset | Hand-reviewed cases with the expected outcome for each |
| Deterministic check | A pass/fail rule computed by code (labels, length, identity) |
| Judge | A second model call that grades comment quality against `judge_notes` |
| Smoke test | One real call against the running service to see that it does something sensible |
| Trace / span | Langfuse's record of one request and the steps inside it |
| Known limitation | A case the design cannot solve yet; excluded from the headline pass rate |

Files to ignore: `app.yaml` and `deploy.sh` are superseded. `src/agent_without_hitl.py`, `check_models.py` and `test_api.py` are of unknown value; check before relying on them.

---

## 15. Cost and run time

These are estimates from the Langfuse traces, not measured totals:

- One classification costs about $0.010 to $0.012 (claude-opus-5-5, about 2k tokens) and takes about 5 to 7 seconds.
- A full 34-case run is therefore roughly $0.35 to $0.40, and `--repeat 3` roughly $1.10.
- `--judge` adds a judge call per comment. Its cost has not been measured.
- Eval runs also create Langfuse traces, because `classify_issue` is decorated.
