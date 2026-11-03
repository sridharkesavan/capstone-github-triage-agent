"""
Eval runner for the GitHub Issue Triage Agent (Phase 4).

Runs the REAL classify_issue() on every case in evals/golden_issues.json and
scores the result. It never connects to GitHub and never goes near the
approval gate, so it is safe to run at any time. It does call the Claude API
(one call per case per repeat), so it costs a little each run.

Usage (from the repo root):
    python3 evals/run_eval.py                  # all cases
    python3 evals/run_eval.py --ids g19,g23    # just a few cases
    python3 evals/run_eval.py --repeat 3       # run each case 3 times, find flaky ones
    python3 evals/run_eval.py --tag baseline   # label the saved results file
"""

import argparse
import collections
import datetime
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

# Must run BEFORE importing src.agent, which reads the API key at import time.
load_dotenv(ROOT / ".env")

from anthropic import Anthropic  # noqa: E402
from src.agent import GitHubTriageAgent  # noqa: E402

GOLDEN = ROOT / "evals" / "golden_issues.json"
RESULTS = ROOT / "evals" / "results"


def make_agent(model):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY not found. Put it in .env at the repo root.")
    # Skip __init__ on purpose: it connects to GitHub, and evals must not need
    # GitHub. classify_issue() only uses self.client and self.model.
    agent = GitHubTriageAgent.__new__(GitHubTriageAgent)
    agent.client = Anthropic(api_key=key)
    agent.model = model
    return agent


def norm(labels):
    if not isinstance(labels, list):
        return []
    return [str(x).strip().lower() for x in labels]


def is_fallback(res):
    """classify_issue() returns canned answers when parsing or the API call fails."""
    reason = res.get("reasoning") or ""
    return (
        res.get("fallback") is True
        or reason == "Default classification due to parsing error"
        or reason.startswith("Error:")
    )


def score(case, res, vocab):
    labels = norm(res.get("suggested_labels"))
    comment = res.get("response_comment")
    comment = comment if isinstance(comment, str) else ""
    got_class = str(res.get("classification", "")).strip().lower()

    checks = {}
    acceptable = case["acceptable_classifications"]
    if acceptable is not None:
        checks["classification"] = got_class in acceptable
    checks["required_labels"] = set(norm(case["labels_required"])) <= set(labels)
    checks["labels_in_vocabulary"] = set(labels) <= vocab
    checks["no_forbidden_labels"] = not (
        set(norm(case.get("forbidden_labels", []))) & set(labels)
    )
    if case["comment_required"]:
        checks["comment_present"] = bool(comment.strip())
    checks["no_forbidden_text"] = not any(
        s.lower() in comment.lower() for s in case.get("forbidden_in_comment", [])
    )
    checks["not_fallback"] = not is_fallback(res)
    return checks, all(checks.values())


def run_one(agent, case):
    issue = {
        "number": int(case["id"][1:]),
        "title": case["title"],
        "body": case["body"],
        "author": "eval",
        "created_at": "",
        "labels": [],
        "url": "",
    }
    start = time.time()
    res = agent.classify_issue(issue)
    return res, round(time.time() - start, 1)


def pct(a, b):
    return f"{a}/{b} ({(100 * a / b):.0f}%)" if b else "n/a"


def main():
    ap = argparse.ArgumentParser(description="Score the triage agent on the golden dataset")
    ap.add_argument("--ids", help="comma-separated case ids, for example g19,g23")
    ap.add_argument("--repeat", type=int, default=1, help="runs per case")
    ap.add_argument("--workers", type=int, default=4, help="parallel API calls")
    ap.add_argument("--model", default="claude-opus-5-5", help="must match src/agent.py")
    ap.add_argument("--tag", default="", help="label added to the results file name")
    args = ap.parse_args()

    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    vocab = set(norm(data["label_vocabulary"]))
    cases = data["cases"]
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
        if not cases:
            sys.exit(f"No cases match --ids {args.ids}")
    case_by_id = {c["id"]: c for c in cases}

    agent = make_agent(args.model)
    jobs = [(c, r) for c in cases for r in range(args.repeat)]
    print(f"Running {len(jobs)} classification(s) on {args.model} ({args.workers} at a time)...")

    def work(job):
        case, r = job
        res, secs = run_one(agent, case)
        checks, ok = score(case, res, vocab)
        print(f"  done {case['id']} (run {r + 1}/{args.repeat})", flush=True)
        return {"id": case["id"], "run": r, "ok": ok, "checks": checks,
                "seconds": secs, "result": res}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        runs = list(pool.map(work, jobs))

    by_case = collections.defaultdict(list)
    for r in runs:
        by_case[r["id"]].append(r)

    # ---- per-case table --------------------------------------------------
    print("\nCASE RESULTS")
    for cid in sorted(by_case):
        rs = by_case[cid]
        passed = sum(r["ok"] for r in rs)
        failed = sorted({k for r in rs for k, v in r["checks"].items() if not v})
        got = ",".join(sorted({str(r["result"].get("classification")) for r in rs}))
        status = "PASS" if passed == len(rs) else ("FLAKY" if passed else "FAIL")
        note = "  (known limitation)" if "known_limitation" in case_by_id[cid] else ""
        extra = f"  failed: {', '.join(failed)}" if failed else ""
        print(f"  {cid}  {status:<5} {passed}/{len(rs)}  class={got:<10}{extra}{note}")

    # ---- summary ---------------------------------------------------------
    counted = [r for r in runs if "known_limitation" not in case_by_id[r["id"]]]
    known = [r for r in runs if "known_limitation" in case_by_id[r["id"]]]
    print("\nSUMMARY (known limitations excluded from the headline)")
    print(f"  Headline pass rate : {pct(sum(r['ok'] for r in counted), len(counted))}")
    if known:
        print(f"  Known limitations  : {pct(sum(r['ok'] for r in known), len(known))}")
    fallbacks = [r for r in runs if not r["checks"]["not_fallback"]]
    print(f"  Fallback answers   : {len(fallbacks)} of {len(runs)} (parse or API failures)")

    print("\n  By check:")
    totals, passes = collections.Counter(), collections.Counter()
    for r in counted:
        for k, v in r["checks"].items():
            totals[k] += 1
            passes[k] += bool(v)
    for k in sorted(totals):
        print(f"    {k:<22} {pct(passes[k], totals[k])}")

    print("\n  By tag:")
    tag_tot, tag_pass = collections.Counter(), collections.Counter()
    for r in counted:
        for t in case_by_id[r["id"]]["tags"]:
            tag_tot[t] += 1
            tag_pass[t] += r["ok"]
    for t in sorted(tag_tot):
        print(f"    {t:<28} {pct(tag_pass[t], tag_tot[t])}")

    flaky = [cid for cid, rs in by_case.items() if 0 < sum(r["ok"] for r in rs) < len(rs)]
    if args.repeat > 1:
        print(f"\n  Flaky cases (pass only some runs): {', '.join(sorted(flaky)) or 'none'}")

    # ---- save ------------------------------------------------------------
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"run_{stamp}" + (f"_{args.tag}" if args.tag else "") + ".json"
    out = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "repeat": args.repeat,
        "cases_run": len(cases),
        "headline": {
            "passed": sum(r["ok"] for r in counted),
            "total": len(counted),
        },
        "fallbacks": len(fallbacks),
        "runs": runs,
    }
    (RESULTS / name).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: evals/results/{name}")


if __name__ == "__main__":
    main()
