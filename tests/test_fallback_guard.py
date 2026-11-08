"""Fallback guard: a failed classification must be marked and must never become a proposal.

classify_issue() returns a canned answer when the API call fails or the reply cannot be parsed.
That answer looks like a normal triage result (question, needs-triage), so it is marked with
fallback=True and propose_github_action() refuses it. No network: the Anthropic client is a fake.
"""
import json

import pytest

import src.agent as agent_module
from src.agent import GitHubTriageAgent
from src.hitl_gate import HITLGate

ISSUE = {"number": 7, "title": "Login button not working", "body": "It does nothing."}

GOOD_REPLY = json.dumps(
    {
        "issue_number": 0,
        "issue_title": "x",
        "classification": "bug",
        "confidence": 0.9,
        "suggested_labels": ["bug"],
        "response_comment": "Thanks for reporting this. A maintainer will review this.",
        "reasoning": "The title describes broken behavior.",
    }
)


class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeBlock(text)]
        self.stop_reason = "end_turn"


class FakeMessages:
    def __init__(self, behavior):
        self.behavior = behavior

    def create(self, **kwargs):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return FakeResponse(self.behavior)


class FakeClient:
    def __init__(self, behavior):
        self.messages = FakeMessages(behavior)


@pytest.fixture(autouse=True)
def no_tracing(monkeypatch):
    # Keep unit tests from sending anything to Langfuse
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    monkeypatch.setattr(agent_module, "update_generation", lambda **kwargs: None)


def make_agent(behavior):
    agent = GitHubTriageAgent.__new__(GitHubTriageAgent)  # skip __init__: no keys, no GitHub
    agent.client = FakeClient(behavior)
    agent.model = "test-model"
    agent.enable_hitl = True
    agent.hitl_gate = HITLGate(interactive=False)
    return agent


def test_api_error_is_marked_as_fallback_and_not_proposed():
    agent = make_agent(RuntimeError("boom"))
    result = agent.classify_issue(ISSUE)
    assert result["fallback"] is True
    assert result["issue_number"] == 7
    agent.propose_github_action(result)
    assert agent.hitl_gate.get_pending_actions() == []


def test_unparseable_reply_is_marked_as_fallback_and_not_proposed():
    agent = make_agent("this is not json at all")
    result = agent.classify_issue(ISSUE)
    assert result["fallback"] is True  # must survive the label guardrail that runs afterwards
    agent.propose_github_action(result)
    assert agent.hitl_gate.get_pending_actions() == []


def test_good_reply_is_not_marked_and_is_proposed():
    agent = make_agent(GOOD_REPLY)
    result = agent.classify_issue(ISSUE)
    assert result.get("fallback") is not True
    agent.propose_github_action(result)
    pending = agent.hitl_gate.get_pending_actions()
    assert [a.issue_number for a in pending] == [7]


def test_propose_refuses_a_marked_result_even_with_labels_and_comment():
    agent = make_agent(GOOD_REPLY)
    result = agent.classify_issue(ISSUE)
    result["fallback"] = True
    agent.propose_github_action(result)
    assert agent.hitl_gate.get_pending_actions() == []
