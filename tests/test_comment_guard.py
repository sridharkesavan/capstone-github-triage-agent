"""Comment guard: length, links and promises are checked in code, on every classification.

Unit tests check the text rules. Integration tests run classify_issue with a fake Anthropic client
(no network) and check that a comment that breaks the policy is removed and never proposed.
"""
import json

import pytest

import src.agent as agent_module
from src.agent import GitHubTriageAgent
from src.comment_guard import (
    MAX_COMMENT_CHARS,
    check_comment,
    enforce_comment_policy,
    has_foreign_link,
    has_promise,
)
from src.hitl_gate import HITLGate

# ---------------------------------------------------------------- unit: promises


@pytest.mark.parametrize(
    "comment",
    [
        "We will fix this next week.",
        "We'll fix this soon.",
        "I'll add documentation for this.",
        "This will be fixed in the next release.",
        "We'll reopen this issue once the tests pass.",
        "A fix will land within 2 days.",
        "We are working on a fix.",
        "We promise to look at it by tomorrow.",
        "修正します。",
        "明日までに対応します。",
        "必ず修正します。",
    ],
)
def test_promises_are_detected(comment):
    assert has_promise(comment) is True


@pytest.mark.parametrize(
    "comment",
    [
        "Thanks for reporting this. A maintainer will review this.",
        "担当者が確認します。",
        "Could you share the steps to reproduce and the error message?",
        "We'll look into this together once you share the logs.",
        "Did this start happening this week?",
    ],
)
def test_harmless_comments_are_not_flagged_as_promises(comment):
    assert has_promise(comment) is False


# ------------------------------------------------------------------ unit: links


def test_link_not_in_the_issue_is_flagged():
    assert has_foreign_link("See https://example.com/guide for details.", "My button does nothing.") is True


def test_link_that_the_issue_already_contains_is_allowed():
    issue_text = "Logs are at https://example.com/logs/123 if that helps."
    assert has_foreign_link("Thanks for the logs at https://example.com/logs/123.", issue_text) is False


def test_markdown_link_to_a_foreign_site_is_flagged():
    assert has_foreign_link("See [the docs](https://evil.example/x) here.", "no links in the issue") is True


def test_comment_without_links_is_fine():
    assert has_foreign_link("Could you share more details?", "anything") is False


# ----------------------------------------------------------------- unit: length


def test_comment_at_the_limit_passes_and_over_the_limit_fails():
    assert "too_long" not in check_comment("x" * MAX_COMMENT_CHARS)
    assert "too_long" in check_comment("x" * (MAX_COMMENT_CHARS + 1))


def test_several_violations_are_all_reported():
    comment = "We will fix this. See https://example.com/a " + "x" * MAX_COMMENT_CHARS
    assert check_comment(comment, "nothing here") == ["too_long", "link", "promise"]


# ----------------------------------------------------- unit: enforce_comment_policy


def make_result(comment):
    return {
        "issue_number": 7,
        "issue_title": "Login button not working",
        "classification": "bug",
        "confidence": 0.9,
        "suggested_labels": ["bug"],
        "response_comment": comment,
        "reasoning": "r",
    }


ISSUE = {"number": 7, "title": "Login button not working", "body": "It does nothing."}


def test_enforce_leaves_a_clean_comment_untouched():
    result = make_result("Thanks for reporting this. A maintainer will review this.")
    assert enforce_comment_policy(result, ISSUE) is result


def test_enforce_removes_a_bad_comment_and_keeps_the_labels():
    result = make_result("We will fix this tomorrow.")
    out = enforce_comment_policy(result, ISSUE)
    assert out["response_comment"] is None
    assert out["removed_comment"] == "We will fix this tomorrow."
    assert out["comment_violations"] == ["promise"]
    assert out["suggested_labels"] == ["bug"]
    assert result["response_comment"] == "We will fix this tomorrow."  # the input is not modified


def test_enforce_ignores_a_missing_comment():
    result = make_result(None)
    assert enforce_comment_policy(result, ISSUE) is result


# ------------------------------------------------- integration: through classify_issue


class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeBlock(text)]
        self.stop_reason = "end_turn"


class FakeMessages:
    def __init__(self, text):
        self.text = text

    def create(self, **kwargs):
        return FakeResponse(self.text)


class FakeClient:
    def __init__(self, text):
        self.messages = FakeMessages(text)


@pytest.fixture(autouse=True)
def no_tracing(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    monkeypatch.setattr(agent_module, "update_generation", lambda **kwargs: None)


def make_agent(comment):
    reply = json.dumps(
        {
            "issue_number": 0,
            "issue_title": "x",
            "classification": "bug",
            "confidence": 0.9,
            "suggested_labels": ["bug"],
            "response_comment": comment,
            "reasoning": "The title describes broken behavior.",
        }
    )
    agent = GitHubTriageAgent.__new__(GitHubTriageAgent)  # skip __init__: no keys, no GitHub
    agent.client = FakeClient(reply)
    agent.model = "test-model"
    agent.enable_hitl = True
    agent.hitl_gate = HITLGate(interactive=False)
    return agent


def classify_and_propose(comment, issue=ISSUE):
    agent = make_agent(comment)
    result = agent.classify_issue(issue)
    agent.propose_github_action(result)
    return result, agent.hitl_gate.get_pending_actions()


def test_clean_comment_is_proposed_with_its_comment():
    result, pending = classify_and_propose("Thanks for reporting this. A maintainer will review this.")
    assert "comment_violations" not in result
    assert [a.action_type for a in pending] == ["both"]


def test_promise_in_the_model_reply_is_removed_before_proposing():
    result, pending = classify_and_propose("We will fix this tomorrow.")
    assert result["response_comment"] is None
    assert result["comment_violations"] == ["promise"]
    assert [a.action_type for a in pending] == ["add_labels"]  # labels still proposed, comment is not
    assert pending[0].comment is None


def test_foreign_link_in_the_model_reply_is_removed_before_proposing():
    result, pending = classify_and_propose("Please read https://example.com/guide first.")
    assert result["comment_violations"] == ["link"]
    assert pending[0].comment is None


def test_link_from_the_issue_itself_is_kept():
    issue = {"number": 7, "title": "Build fails", "body": "Log: https://example.com/log/9"}
    result, pending = classify_and_propose("Thanks for the log at https://example.com/log/9.", issue)
    assert "comment_violations" not in result
    assert pending[0].comment == "Thanks for the log at https://example.com/log/9."


def test_overlong_comment_in_the_model_reply_is_removed_before_proposing():
    result, pending = classify_and_propose("Thanks. " + "word " * 200)
    assert "too_long" in result["comment_violations"]
    assert pending[0].comment is None
