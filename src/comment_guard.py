"""Deterministic checks on the comment text of a classification result.

The comment policy (config/prompts.py) asks the model for a short comment with no links it was not
given and no promises. The prompt and the LLM judge check that; this module checks it in plain code,
on every classification, so a comment that breaks the policy is never proposed.

Three checks:
  too_long  the comment is over MAX_COMMENT_CHARS characters
  link      the comment contains a URL that does not appear in the issue's own text
  promise   the comment promises a fix, a release, a reopen, a close, added docs or a timeline

A comment with any violation is removed (response_comment becomes None) and the result records
comment_violations and removed_comment. The labels are left alone, because they are checked separately.
A too-long comment is removed, not cut: cutting would drop the required closing line.

Limits: the promise check is a list of patterns, not understanding. It misses promises worded in a way
the patterns do not cover, and it can flag an unusual harmless sentence. URLs written without a scheme
(for example example.com/page) are not detected.
"""
import re

MAX_COMMENT_CHARS = 800

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]\"']+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}>'\"\u300d\u3002\u3001"

_PROMISE_VERBS = (
    "fix|add|implement|release|ship|reopen|close|merge|resolve|patch|document|support|"
    "prioriti[sz]e|deliver|build|write"
)
_PASSIVE_PARTICIPLES = (
    "fixed|added|implemented|released|shipped|reopened|closed|merged|resolved|patched|"
    "documented|supported|prioriti[sz]ed"
)
PROMISE_PATTERNS = [
    re.compile(
        rf"\b(?:we|i|maintainers?|the team|our team)\s*(?:will|'ll|\u2019ll|are going to|am going to|shall)"
        rf"\s+(?:definitely\s+|soon\s+|also\s+|gladly\s+)?(?:{_PROMISE_VERBS})\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\bwill\s+be\s+(?:{_PASSIVE_PARTICIPLES})\b", re.IGNORECASE),
    re.compile(r"\bwe(?:'re|\u2019re| are)\s+(?:working on|fixing|adding|implementing)\b", re.IGNORECASE),
    re.compile(r"\b(?:i|we)\s+(?:promise|guarantee)\b", re.IGNORECASE),
    re.compile(
        r"\bwithin\s+(?:\d+|a|an|one|two|three|a few)\s+(?:hours?|days?|weeks?|months?|business days?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:by|before)\s+(?:tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|"
        r"the end of (?:the )?(?:day|week|month))\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:in the )?next\s+(?:release|version|sprint)\b", re.IGNORECASE),
    re.compile(r"\bETA\b"),
    # Japanese
    re.compile(r"(?:修正|対応|追加|実装|リリース|解決)\s*(?:します|いたします|致します|予定です|する予定)"),
    re.compile(r"(?:明日|今日中|今週中|来週|今月中|来月)(?:までに|中に)?(?:修正|対応|リリース|解決)"),
    re.compile(r"お約束|必ず(?:修正|対応)"),
]


def _normalize_url(url):
    url = url.strip().rstrip(TRAILING_PUNCTUATION).lower()
    return url.rstrip("/")


def has_foreign_link(comment, issue_text):
    """True if the comment has a URL that does not appear in the issue's own text."""
    allowed_text = (issue_text or "").lower()
    for match in URL_RE.findall(comment):
        url = _normalize_url(match)
        if url and url not in allowed_text:
            return True
    return False


def has_promise(comment):
    """True if the comment matches one of the promise patterns."""
    return any(p.search(comment) for p in PROMISE_PATTERNS)


def check_comment(comment, issue_text=""):
    """Return the list of violations found in a comment: 'too_long', 'link', 'promise'."""
    violations = []
    if len(comment) > MAX_COMMENT_CHARS:
        violations.append("too_long")
    if has_foreign_link(comment, issue_text):
        violations.append("link")
    if has_promise(comment):
        violations.append("promise")
    return violations


def enforce_comment_policy(classification, issue):
    """Remove the comment from a classification result if it breaks the comment policy.

    classification: the result dict from classify_issue; issue: the GitHub issue dict (title, body).
    Returns the same dict when the comment is fine or absent, otherwise a copy with response_comment
    set to None, the original text in removed_comment and the reasons in comment_violations.
    """
    comment = classification.get("response_comment")
    if not isinstance(comment, str) or not comment.strip():
        return classification
    issue_text = f"{issue.get('title') or ''}\n{issue.get('body') or ''}"
    violations = check_comment(comment, issue_text)
    if not violations:
        return classification
    result = dict(classification)
    result["removed_comment"] = comment
    result["response_comment"] = None
    result["comment_violations"] = violations
    return result
