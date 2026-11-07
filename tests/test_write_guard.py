"""Write guard: GitHubTools may only write what an approved Action describes.

No network: GitHubTools is built without __init__ and given a fake repo that records calls.
"""
import pytest

import src.tools as tools_module
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


def make_tools():
    tools = GitHubTools.__new__(GitHubTools)  # skip __init__ so nothing connects to GitHub
    tools.repo = FakeRepo()
    return tools


def make_action(n=7, action_type="both", labels=("bug",), comment="Thanks for reporting this."):
    return Action(
        issue_number=n,
        issue_title=f"issue {n}",
        classification="bug",
        action_type=action_type,
        labels=list(labels),
        comment=comment,
    )


def approved_through_gate(action):
    gate = HITLGate(interactive=False)
    gate.propose_action(action)
    assert gate.approve_by_id(action.id) is True
    return gate.pop_approved()[0]


def test_unapproved_action_cannot_write():
    tools = make_tools()
    action = make_action()
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.apply_labels(action)
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.post_comment(action)
    assert tools.repo.log == []


def test_rejected_action_cannot_write():
    tools = make_tools()
    action = make_action()
    gate = HITLGate(interactive=False)
    gate.propose_action(action)
    assert gate.reject_by_id(action.id) is True
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.apply_labels(action)
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.post_comment(action)
    assert tools.repo.log == []


def test_approved_action_writes_exactly_what_was_proposed():
    tools = make_tools()
    action = approved_through_gate(make_action(n=7, labels=("bug", "needs-more-info"), comment="Hello."))
    assert tools.apply_labels(action) is True
    assert tools.post_comment(action) is True
    assert tools.repo.log == [
        ("labels", 7, ["bug", "needs-more-info"]),
        ("comment", 7, "Hello."),
    ]


def test_approval_is_scoped_to_what_was_proposed():
    tools = make_tools()
    labels_only = approved_through_gate(make_action(action_type="add_labels", comment=None))
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.post_comment(labels_only)
    comment_only = approved_through_gate(make_action(action_type="add_comment", labels=()))
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.apply_labels(comment_only)
    assert tools.repo.log == []


@pytest.mark.parametrize(
    "not_an_action",
    [None, 7, {"approved": True, "issue_number": 7, "labels": ["bug"], "comment": "x"}],
)
def test_only_action_objects_are_accepted(not_an_action):
    tools = make_tools()
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.apply_labels(not_an_action)
    with pytest.raises(tools_module.UnapprovedActionError):
        tools.post_comment(not_an_action)
    assert tools.repo.log == []


def test_loose_write_methods_no_longer_exist():
    tools = make_tools()
    assert not hasattr(tools, "add_label")
    assert not hasattr(tools, "add_comment")
