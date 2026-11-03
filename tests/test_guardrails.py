import json
from pathlib import Path

from config.prompts import ALLOWED_LABELS, SYSTEM_PROMPT
from src.guardrails import enforce_label_vocabulary

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "golden_issues.json"


def run(labels):
    return enforce_label_vocabulary({"suggested_labels": labels})


def test_unknown_labels_are_dropped_and_recorded():
    out = run(["bug", "dependencies", "good first issue", "needs-triage"])
    assert out["suggested_labels"] == ["bug", "needs-triage"]
    assert out["dropped_labels"] == ["dependencies", "good first issue"]


def test_case_and_whitespace_are_normalised():
    assert run(["Bug", " QUESTION "])["suggested_labels"] == ["bug", "question"]


def test_duplicate_labels_are_removed():
    assert run(["bug", "bug", "BUG"])["suggested_labels"] == ["bug"]


def test_empty_result_falls_back_to_default_label():
    assert run(["invented"])["suggested_labels"] == ["needs-triage"]
    assert run([])["suggested_labels"] == ["needs-triage"]


def test_non_list_labels_do_not_crash():
    assert run(None)["suggested_labels"] == ["needs-triage"]
    assert run("bug")["suggested_labels"] == ["needs-triage"]


def test_prompt_lists_every_allowed_label():
    for label in ALLOWED_LABELS:
        assert label in SYSTEM_PROMPT


def test_dataset_vocabulary_matches_code():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(data["label_vocabulary"]) == sorted(ALLOWED_LABELS)
