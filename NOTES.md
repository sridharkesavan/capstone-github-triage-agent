# Working notes

GitHub Issue Triage Agent (capstone). Last updated 2026-11-08.

Keep this file short. The detail lives in `Phase4.md` (start with "Getting started: step by step"). Update this file when the state, a decision or the open list changes.

## Current state

- Phases 1 to 4 are done and deployed. Phase 4 is done with open items (below).
- Cloud Run: project `github-triage-agent-513401`, service `github-triage-agent`, region `us-central1`, private, one instance. Latest revision `github-triage-agent-00013-zzr`, 100% of traffic. The revision was created after the last code commit.
- Live smoke test: 5 of 5 issues proposed, numbers #1 to #5 correct (rerun on revision 00013). A Langfuse trace from Cloud Run was checked (cost counted once).
- Command-line execute path fixed (2026-11-08): `execute_approved_actions` saves the approval log and then uses `pop_approved()`, so each approval is written once. `approval_log.json` and `triage_results.json` are no longer tracked in git.
- Write guard (2026-11-08): `GitHubTools` writes only through `apply_labels(action)` and `post_comment(action)`, which raise `UnapprovedActionError` unless given an approved `Action` that covers the write. 25 tests pass (`tests/test_write_guard.py` has 8, `tests/test_cli_execute_once.py` has 5). Checked by hand with a local approve and execute.
- Evals: dataset v5, 34 cases. Deterministic checks 99/99 over 33 cases x 3 runs (g18 is a known limitation, 0/3), no flaky cases, 0 fallbacks.
- Judged run: 32/33 before g01's test note was loosened (see decisions).
- Model: `claude-opus-5-5` through the Anthropic SDK. Google ADK is not used.
- Branch is `master`, not `main`.

## Open work, in order

1. Remaining deterministic guardrails (not written): block proposals made from fallback results; a link check on comments; a promise-phrase flag; a length cap.
2. Trace the judge call and each eval run in Langfuse, tagged by case id.
3. Run `--judge --repeat 3` on the full set (the judge has run once per case, and only g01 was repeated).
4. Remove `issue_number` and `issue_title` from the JSON schema in `config/prompts.py`, because the model cannot know them. Separate change, run the evals before and after.
5. Add a golden case with a complete bug report that must not get `needs-more-info`, to test over-triggering.
6. Add a "[body truncated]" marker when a body is cut at 2000 characters, so a comment never blames the reporter for our cut.
7. Remove `google-adk==0.1.0` from `requirements.txt` (unused).
8. Check files of unknown value before relying on them: `src/agent_without_hitl.py`, `check_models.py`, `test_api.py`. `app.yaml` and `deploy.sh` are superseded.
9. Later, optional: close the forgery gap in the write guard (the gate keeps a private registry of approved ids that the tools check), spam/invalid category, persistent approvals (Firestore), append-only audit log, port to Google ADK with the eval suite as a safety net, Phase 5 enterprise simulation.

## Decisions

- Label vocabulary (7): `bug`, `enhancement`, `question`, `documentation`, `duplicate`, `needs-triage`, `needs-more-info`. Enforced in the prompt and in code.
- Comment policy: acknowledge, short hints grounded in the issue, ask for missing details, no promises, under 800 characters, reply in the reporter's language, no invented project facts. Japanese issues get a Japanese reply ending "担当者が確認します。"
- Issue number and title come from GitHub in code, never from the model.
- Body cutoff is 2000 characters (was 500; the 500 cutoff hid the real problem in g29).
- g01 got `judge_notes` in dataset v5 because judged runs flipped between two acceptable comment styles. The test was loosened. The agent was not changed and still varies between the two styles.
- Implicit duplicates (g18) are a known limitation: the classifier sees one issue at a time.
- Write guard design: raw write methods are private; approval is scoped to what the action proposed (labels or comment); the old public names were removed so a stray caller fails loudly. Kept small on purpose: it stops accidents, not forgery.
- No separate handoff files from here on. `Phase4.md` and this file are the record.

## Known limitations

- Pending approvals live in memory and reset when the instance scales to zero, so Cloud Run runs one instance with one gunicorn worker.
- A failed classification still looks like a normal proposal until the fallback guardrail (open item 1) exists.
- The write guard stops accidents, not forgery: `Action.approved` is a plain attribute that code can set by hand. Anyone holding a PyGithub client can also write directly.
- Spam has no category: issues #4 and #5 get labels but no comment.
- The judge is the same model family as the agent and does not check whether a comment's questions fit the issue (seen on g34).
- The dataset was drafted by the assistant and reviewed by the owner.

## Where things live

- Code repo (private): `sridharkesavan/capstone-github-triage-agent`.
- Repo the agent triages (`GITHUB_REPO`): `sridharkesavan/ai-agents-from-scratch`, test issues #1 to #5. `/execute` writes real comments there.
- Langfuse: Japan region, `https://jp.cloud.langfuse.com`. Keys in `.env` locally and in Secret Manager on Cloud Run.
- Local server on port 8081 (`PORT=8081 python3 main.py`). The Cloud Run proxy on port 9090, in its own terminal tab.

## Working conventions

- One change at a time. Keep the judge fixed while changing the prompt.
- Read the actual replies, not only the score.
- Log every dataset edit in the `changelog` field and bump `version`.
- Edit files with guarded patch scripts that stop if an anchor is missing or appears twice.
- Smoke-test the live service after every deploy and check a fresh trace.
- In zsh, do not put `#` comment lines in pasted commands, and quote globs such as `--include="*.py"`.
