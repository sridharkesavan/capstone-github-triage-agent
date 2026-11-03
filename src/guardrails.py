"""
Deterministic guardrails: plain code that checks and cleans model output.

They run no matter what the model decided. A model can have a good day and a
bad day. Code does not have moods.
"""

from config.prompts import ALLOWED_LABELS

DEFAULT_LABEL = "needs-triage"


def enforce_label_vocabulary(result):
    """Keep only labels from the approved list.

    Anything else is removed and recorded in result["dropped_labels"], so evals
    and reviewers can see what the model tried to add. If nothing valid is
    left, fall back to the safe default label.
    """
    if not isinstance(result, dict):
        return result

    allowed = {label.lower(): label for label in ALLOWED_LABELS}
    raw = result.get("suggested_labels")
    raw = raw if isinstance(raw, list) else []

    kept, dropped = [], []
    for label in raw:
        key = str(label).strip().lower()
        if key in allowed:
            if allowed[key] not in kept:
                kept.append(allowed[key])
        else:
            dropped.append(str(label))

    if not kept:
        kept = [DEFAULT_LABEL]

    result["suggested_labels"] = kept
    result["dropped_labels"] = dropped
    return result
