from src.hitl_gate import HITLGate, Action


def make(n):
    return Action(issue_number=n, issue_title=f"issue {n}", classification="bug",
                  action_type="add_labels", labels=["x"], comment=None)


def new_gate():
    return HITLGate(interactive=False)


def test_only_approved_actions_are_executed():
    # The cloud bug: approve #4, reject #3, but #3 got written.
    gate = new_gate()
    a4, a3, a2 = make(4), make(3), make(2)
    for a in (a4, a3, a2):
        gate.propose_action(a)
    gate.approve_by_id(a4.id)
    gate.reject_by_id(a3.id)
    assert [a.issue_number for a in gate.pop_approved()] == [4]


def test_approval_survives_position_shifts():
    # Positions shift after every approve/reject; ids must not.
    gate = new_gate()
    acts = [make(n) for n in (1, 2, 3, 4)]
    for a in acts:
        gate.propose_action(a)
    gate.approve_by_id(acts[3].id)
    gate.approve_by_id(acts[0].id)
    gate.reject_by_id(acts[1].id)
    assert sorted(a.issue_number for a in gate.pop_approved()) == [1, 4]
    assert [a.issue_number for a in gate.get_pending_actions()] == [3]


def test_approved_action_executes_only_once():
    gate = new_gate()
    a = make(4)
    gate.propose_action(a)
    gate.approve_by_id(a.id)
    assert len(gate.pop_approved()) == 1
    assert gate.pop_approved() == []


def test_unknown_id_is_not_approved():
    gate = new_gate()
    gate.propose_action(make(4))
    assert gate.approve_by_id("nope") is False
    assert gate.pop_approved() == []


def test_clear_pending_drops_old_runs():
    gate = new_gate()
    gate.propose_action(make(4))
    gate.clear_pending()
    assert gate.get_pending_actions() == []
