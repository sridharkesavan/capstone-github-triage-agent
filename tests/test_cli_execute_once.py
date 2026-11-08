"""Command-line path: execute_approved_actions must write each approval once.

No network and no real files in the repo: the agent is built without __init__, GitHubTools gets a
fake repo that records calls, and the test runs in a temporary directory because
save_approvals() writes approval_log.json into the current directory.
"""
import json

import pytest

from src.agent import GitHubTriageAgent
from src.hitl_gate import Action, HITLGate
from src.tools import GitHubTools


class FakeIssue:
    def __init__(self, log, number):
        self.log = log
        self.number = number

    def add_to_labels(self, *labels):
        self.log.append(("labels", self.number, list(labels)))

    def create_comment(self, text):
        self.log.append(("comment", self.number, text))


class FakeRepo:
    def __init__(self):
        self.log = []

    def get_issue(self, number):
        return FakeIssue(self.log, number)


def make_agent():
    tools = GitHubTools.__new__(GitHubTools)  # skip __init__ so nothing connects to GitHub
    tools.repo = FakeRepo()
    agent = GitHubTriageAgent.__new__(GitHubTriageAgent)  # skip __init__ so no keys are needed
    agent.enable_hitl = True
    agent.hitl_gate = HITLGate(interactive=False)
    agent.gh_tools = tools
    return agent


def make_action(n):
    return Action(
        issue_number=n,
        issue_title=f"issue {n}",
        classification="bug",
        action_type="both",
        labels=["bug"],
        comment=f"Comment for {n}.",
    )


@pytest.fixture(autouse=True)
def in_temp_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_second_call_does_not_write_the_same_approval_again():
    agent = make_agent()
    action = make_action(7)
    agent.hitl_gate.propose_action(action)
    assert agent.hitl_gate.approve_by_id(action.id) is True

    agent.execute_approved_actions()
    agent.execute_approved_actions()

    assert agent.gh_tools.repo.log == [
        ("labels", 7, ["bug"]),
        ("comment", 7, "Comment for 7."),
    ]


def test_approvals_are_taken_out_of_the_gate_when_executed():
    agent = make_agent()
    action = make_action(7)
    agent.hitl_gate.propose_action(action)
    agent.hitl_gate.approve_by_id(action.id)

    agent.execute_approved_actions()

    assert agent.hitl_gate.get_approved_actions() == []


def test_command_line_style_index_approval_executes_once():
    # interactive_approve() approves by index, so exercise that route as well
    agent = make_agent()
    agent.hitl_gate.propose_action(make_action(3))
    assert agent.hitl_gate.approve_action(0) is True

    agent.execute_approved_actions()
    agent.execute_approved_actions()

    assert [entry[:2] for entry in agent.gh_tools.repo.log] == [("labels", 3), ("comment", 3)]


def test_rejected_and_pending_actions_are_not_written():
    agent = make_agent()
    a1, a2, a3 = make_action(1), make_action(2), make_action(3)
    for a in (a1, a2, a3):
        agent.hitl_gate.propose_action(a)
    agent.hitl_gate.approve_by_id(a2.id)
    agent.hitl_gate.reject_by_id(a1.id)

    agent.execute_approved_actions()

    assert {entry[1] for entry in agent.gh_tools.repo.log} == {2}


def test_approval_log_still_records_the_approved_action():
    # The log must be saved before the approvals are taken out of the gate.
    agent = make_agent()
    action = make_action(7)
    agent.hitl_gate.propose_action(action)
    agent.hitl_gate.approve_by_id(action.id)

    agent.execute_approved_actions()

    log = json.load(open("approval_log.json"))
    assert [entry["issue_number"] for entry in log["approved"]] == [7]
