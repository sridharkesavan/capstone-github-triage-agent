"""
System prompts and classification logic for GitHub issue triage agent.
"""

SYSTEM_PROMPT = """You are a GitHub issue triage expert. Your job is to analyze GitHub issues and classify them.

For each issue, you will:
1. Read the title and body
2. Classify it into ONE category: bug, feature, question, or duplicate
3. Suggest appropriate labels
4. Draft a professional response comment (if needed)

Classification rules:
- **bug**: Something is broken, not working as expected, or causing errors
- **feature**: A request for new functionality or enhancement
- **question**: User asking for help, clarification, or documentation
- **duplicate**: The issue has already been reported or addressed elsewhere

Output format (JSON):
{
  "issue_number": <int>,
  "issue_title": "<string>",
  "classification": "<bug|feature|question|duplicate>",
  "confidence": <0.0-1.0>,
  "suggested_labels": ["label1", "label2"],
  "response_comment": "<string or null>",
  "reasoning": "<brief explanation>"
}

Always be professional, helpful, and constructive. If unsure, pick the best fit and explain in reasoning.
"""

CLASSIFICATION_PROMPT = """
Analyze this GitHub issue and classify it:

Title: {title}
Body: {body}

Provide your classification in the JSON format specified in the system prompt.
"""

# Label mappings
LABEL_SUGGESTIONS = {
    "bug": ["bug", "needs-triage"],
    "feature": ["enhancement", "needs-triage"],
    "question": ["question", "documentation"],
    "duplicate": ["duplicate"],
}

# Response templates
RESPONSE_TEMPLATES = {
    "bug": "Thank you for reporting this issue. We've classified this as a bug. The team will investigate and get back to you soon.",
    "feature": "Thank you for the feature request. We've added this to our backlog for consideration.",
    "question": "Thank you for the question. This appears to be a support question. Please check our documentation or reach out on our support channels.",
    "duplicate": "Thank you for your report. This appears to be a duplicate of an existing issue. Please refer to the linked issue for updates.",
}